"""UBA Daily Loss — Equity Baseline 대비 당일 손익 (누적 평가손익 금지)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.broker.account_models import BrokerAccountSnapshotEntity
from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
)
from stock_platform.broker.kiwoom.equity_policy import (
    KIWOOM_EQUITY_V1_IMMEDIATE_CASH,
    KIWOOM_EQUITY_V2_SETTLEMENT_AWARE,
    compute_kiwoom_equity_for_risk,
    default_policy_for_new_kiwoom_baseline,
    resolve_kiwoom_policy_for_baseline,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.live_safety_audit import emit_live_safety_audit
from stock_platform.risk_engine.uba_daily_equity_baseline_entities import (
    UbaDailyEquityBaselineEntity,
)
from stock_platform.trading.account_models import UserBrokerAccount


ZERO = Decimal("0")
_KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True, slots=True)
class UbaDailyLossBreakdown:
    user_broker_account_id: int
    trading_date: date
    broker_code: str
    execution_count: int
    buy_fill_count: int
    sell_fill_count: int
    position_count: int
    snapshot_count: int
    opening_equity: Decimal
    closing_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    fees: Decimal
    current_daily_pnl: Decimal
    current_daily_loss: Decimal
    max_daily_loss_limit: Decimal
    remaining_daily_loss_capacity: Decimal
    baseline_at: datetime | None
    baseline_source: str | None
    correlation_id: str
    equity_policy_version: str | None = None
    equity_source: str | None = None
    pending_settlement_cash: str | None = None
    legacy_equity: str | None = None
    external_cash_flow_gap: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_broker_account_id": self.user_broker_account_id,
            "trading_date": self.trading_date.isoformat(),
            "broker_code": self.broker_code,
            "execution_count": self.execution_count,
            "buy_fill_count": self.buy_fill_count,
            "sell_fill_count": self.sell_fill_count,
            "position_count": self.position_count,
            "snapshot_count": self.snapshot_count,
            "opening_equity": str(self.opening_equity),
            "closing_equity": str(self.closing_equity),
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": str(self.unrealized_pnl),
            "fees": str(self.fees),
            "current_daily_pnl": str(self.current_daily_pnl),
            "current_daily_loss": str(self.current_daily_loss),
            "max_daily_loss_limit": str(self.max_daily_loss_limit),
            "remaining_daily_loss_capacity": str(
                self.remaining_daily_loss_capacity
            ),
            "baseline_at": (
                self.baseline_at.isoformat() if self.baseline_at else None
            ),
            "baseline_source": self.baseline_source,
            "correlation_id": self.correlation_id,
            "equity_policy_version": self.equity_policy_version,
            "equity_source": self.equity_source,
            "pending_settlement_cash": self.pending_settlement_cash,
            "legacy_equity": self.legacy_equity,
            "external_cash_flow_gap": self.external_cash_flow_gap,
            "scope": f"UBA:{self.user_broker_account_id}",
        }


def snapshot_equity(
    account: BrokerAccountSnapshotEntity,
    *,
    policy_version: str | None = None,
) -> Decimal:
    """
    Daily Loss용 equity.

    KIWOOM: settlement-aware policy (V1/V2).
    UPBIT/PAPER/기타: 예수금 + 보유평가 (기존 공식 유지).
    누적 total_profit_loss 사용 금지.
    """

    broker = str(getattr(account, "broker_code", "") or "").upper()
    if broker == "KIWOOM":
        breakdown = compute_kiwoom_equity_for_risk(
            account,
            policy_version=policy_version,
        )
        return breakdown.equity_for_risk

    deposit = Decimal(str(account.deposit_amount or ZERO))
    evaluation = Decimal(str(account.total_evaluation_amount or ZERO))
    return (deposit + evaluation).quantize(Decimal("0.01"))


def snapshot_equity_detail(
    account: BrokerAccountSnapshotEntity,
    *,
    policy_version: str | None = None,
) -> dict[str, Any]:
    """additive provenance — UI/진단용."""

    broker = str(getattr(account, "broker_code", "") or "").upper()
    if broker == "KIWOOM":
        return compute_kiwoom_equity_for_risk(
            account,
            policy_version=policy_version,
        ).to_raw_dict()
    equity = snapshot_equity(account, policy_version=policy_version)
    return {
        "equity_for_risk": str(equity),
        "equity_source": "CASH_PLUS_STOCK_EVALUATION",
        "equity_policy_version": None,
        "pending_settlement_cash": "0",
        "legacy_equity": str(equity),
        "external_cash_flow_gap": None,
    }


def daily_loss_from_pnl(daily_pnl: Decimal) -> Decimal:
    """이익이면 0, 손실이면 절댓값."""

    return max(-daily_pnl, ZERO)


class UbaDailyLossService:
    """
    Preflight / Monitor 공통.
    Daily PnL = closing_equity - opening_equity (당일 Baseline).
    opening/current는 동일 equity_policy_version을 사용한다.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._snapshots = BrokerAccountSnapshotRepository(session)

    def resolve_equity_policy(
        self,
        *,
        broker_code: str,
        baseline: UbaDailyEquityBaselineEntity | None,
        for_new_baseline: bool = False,
    ) -> str | None:
        """KIWOOM만 version 관리. 그 외는 None(기존 공식)."""

        if str(broker_code).upper() != "KIWOOM":
            return None
        if for_new_baseline and baseline is None:
            return default_policy_for_new_kiwoom_baseline()
        if baseline is None:
            return default_policy_for_new_kiwoom_baseline()
        return resolve_kiwoom_policy_for_baseline(
            getattr(baseline, "equity_policy_version", None)
        )

    def diagnose(
        self,
        *,
        user_broker_account_id: int,
        loss_limit: Decimal,
        trading_date: date | None = None,
    ) -> UbaDailyLossBreakdown:
        uba_id = int(user_broker_account_id)
        day = trading_date or datetime.now(_KST).date()
        uba = self._session.get(UserBrokerAccount, uba_id)
        if uba is None:
            raise LookupError(f"UBA not found: {uba_id}")

        account, positions = self._snapshots.get_active_by_uba(uba_id)
        if account is None:
            raise LookupError("ACTIVE broker snapshot missing")

        broker_code = str(account.broker_code).upper()
        baseline = self._get_baseline(uba_id, day)
        # mid-day: 기존 baseline version 유지 (NULL → KIWOOM V1)
        policy = self.resolve_equity_policy(
            broker_code=broker_code,
            baseline=baseline,
            for_new_baseline=False,
        )
        closing = snapshot_equity(account, policy_version=policy)
        detail = snapshot_equity_detail(account, policy_version=policy)
        opening = (
            Decimal(str(baseline.opening_equity))
            if baseline is not None
            else closing
        )
        daily_pnl = (closing - opening).quantize(Decimal("0.01"))
        exec_stats = self._execution_stats(uba_id, day)
        realized = ZERO
        fees = ZERO
        unrealized = daily_pnl - realized
        loss = daily_loss_from_pnl(daily_pnl)
        remaining = (loss_limit - loss).quantize(Decimal("0.01"))
        snap_count = int(
            self._session.scalar(
                select(func.count())
                .select_from(BrokerAccountSnapshotEntity)
                .where(
                    BrokerAccountSnapshotEntity.user_broker_account_id
                    == uba_id
                )
            )
            or 0
        )
        return UbaDailyLossBreakdown(
            user_broker_account_id=uba_id,
            trading_date=day,
            broker_code=broker_code,
            execution_count=exec_stats["total"],
            buy_fill_count=exec_stats["buy"],
            sell_fill_count=exec_stats["sell"],
            position_count=len(positions),
            snapshot_count=snap_count,
            opening_equity=opening,
            closing_equity=closing,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            fees=fees,
            current_daily_pnl=daily_pnl,
            current_daily_loss=loss,
            max_daily_loss_limit=loss_limit,
            remaining_daily_loss_capacity=remaining,
            baseline_at=baseline.baseline_at if baseline else None,
            baseline_source=baseline.source_code if baseline else None,
            correlation_id=f"uba-dl-{uba_id}-{day.isoformat()}",
            equity_policy_version=policy or detail.get("equity_policy_version"),
            equity_source=detail.get("equity_source"),
            pending_settlement_cash=detail.get("pending_settlement_cash"),
            legacy_equity=detail.get("legacy_equity"),
            external_cash_flow_gap=detail.get("external_cash_flow_gap"),
        )

    def ensure_baseline(
        self,
        *,
        user_broker_account_id: int,
        opening_equity: Decimal,
        trading_date: date | None = None,
        source_code: str = "FIRST_OBSERVED",
        actor: str = "SYSTEM",
        broker_code: str | None = None,
        force_replace: bool = False,
        equity_policy_version: str | None = None,
    ) -> UbaDailyEquityBaselineEntity:
        """당일 Baseline 없으면 생성. force_replace 시 재설정(정정)."""

        uba_id = int(user_broker_account_id)
        day = trading_date or datetime.now(_KST).date()
        existing = self._get_baseline(uba_id, day)
        corr = f"uba-baseline-{uba_id}-{day.isoformat()}-{uuid.uuid4().hex[:8]}"
        if existing is not None and not force_replace:
            return existing
        if existing is not None and force_replace:
            before = str(existing.opening_equity)
            existing.opening_equity = Decimal(str(opening_equity))
            existing.source_code = source_code
            existing.created_by = actor
            existing.correlation_id = corr
            existing.baseline_at = datetime.now(timezone.utc)
            if broker_code:
                existing.broker_code = broker_code
            if equity_policy_version is not None:
                existing.equity_policy_version = equity_policy_version
            self._session.flush()
            emit_live_safety_audit(
                self._session,
                event_type="UBA_DAILY_LOSS_BASELINE_RESET",
                actor=actor,
                run_id=corr,
                user_id=None,
                account_id=uba_id,
                strategy_id=None,
                detail={
                    "before_opening_equity": before,
                    "after_opening_equity": str(opening_equity),
                    "trading_date": day.isoformat(),
                    "source_code": source_code,
                    "equity_policy_version": equity_policy_version,
                },
                commit=False,
            )
            return existing

        # 신규 baseline — KIWOOM이면 V2 stamp
        policy = equity_policy_version
        if policy is None and str(broker_code or "").upper() == "KIWOOM":
            policy = default_policy_for_new_kiwoom_baseline()

        row = UbaDailyEquityBaselineEntity(
            user_broker_account_id=uba_id,
            trading_date=day,
            currency_code="KRW",
            opening_equity=Decimal(str(opening_equity)),
            source_code=source_code,
            equity_policy_version=policy,
            correlation_id=corr,
            broker_code=broker_code,
            baseline_at=datetime.now(timezone.utc),
            created_by=actor,
        )
        self._session.add(row)
        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type="UBA_DAILY_LOSS_BASELINE_CREATED",
            actor=actor,
            run_id=corr,
            user_id=None,
            account_id=uba_id,
            strategy_id=None,
            detail={
                "opening_equity": str(opening_equity),
                "trading_date": day.isoformat(),
                "source_code": source_code,
                "equity_policy_version": policy,
            },
            commit=False,
        )
        return row

    def recalculate_and_persist(
        self,
        *,
        user_broker_account_id: int,
        loss_limit: Decimal,
        actor: str,
        reset_baseline_if_no_executions: bool = True,
    ) -> UbaDailyLossBreakdown:
        """
        오염된 lifetime PnL 기반 daily_loss 정정.
        당일 체결 0이면 Baseline=현재 equity (상속 손실 제거).
        """

        from stock_platform.risk_engine.daily_loss_models import (
            DailyLossMonitorStatus,
            DailyLossSnapshot,
        )
        from stock_platform.risk_engine.daily_loss_repository import (
            AccountDailyLossRepository,
        )
        from stock_platform.trading.account_masking import mask_account_number

        uba_id = int(user_broker_account_id)
        day = datetime.now(_KST).date()
        account, _positions = self._snapshots.get_active_by_uba(uba_id)
        if account is None:
            raise LookupError("ACTIVE broker snapshot missing")

        broker_code = str(account.broker_code).upper()
        existing = self._get_baseline(uba_id, day)
        if reset_baseline_if_no_executions:
            stats_probe = self._execution_stats(uba_id, day)
            will_replace = stats_probe["total"] == 0 and existing is not None
        else:
            will_replace = False
        if will_replace or existing is None:
            policy = (
                default_policy_for_new_kiwoom_baseline()
                if broker_code == "KIWOOM"
                else None
            )
        else:
            policy = self.resolve_equity_policy(
                broker_code=broker_code,
                baseline=existing,
                for_new_baseline=False,
            )

        equity = snapshot_equity(account, policy_version=policy)
        stats = self._execution_stats(uba_id, day)
        before = self.diagnose(
            user_broker_account_id=uba_id, loss_limit=loss_limit, trading_date=day
        )

        if reset_baseline_if_no_executions and stats["total"] == 0:
            self.ensure_baseline(
                user_broker_account_id=uba_id,
                opening_equity=equity,
                trading_date=day,
                source_code="RECALC_NO_EXECUTIONS",
                actor=actor,
                broker_code=broker_code,
                force_replace=True,
                equity_policy_version=policy,
            )
        else:
            self.ensure_baseline(
                user_broker_account_id=uba_id,
                opening_equity=(
                    equity
                    if before.baseline_source is None
                    else before.opening_equity
                ),
                trading_date=day,
                source_code="FIRST_OBSERVED",
                actor=actor,
                broker_code=broker_code,
                force_replace=False,
                equity_policy_version=policy,
            )

        after = self.diagnose(
            user_broker_account_id=uba_id, loss_limit=loss_limit, trading_date=day
        )
        status = (
            DailyLossMonitorStatus.SAFE
            if after.current_daily_loss < loss_limit
            else DailyLossMonitorStatus.LIMIT_REACHED
        )
        snap = DailyLossSnapshot(
            user_broker_account_id=uba_id,
            paper_account_id=None,
            broker_code=broker_code,
            masked_account_ref=mask_account_number(account.account_number),
            trading_date=day.isoformat(),
            currency="KRW",
            realized_profit_loss=after.realized_pnl,
            unrealized_profit_loss=after.unrealized_pnl,
            combined_profit_loss=after.current_daily_pnl,
            current_loss_amount=after.current_daily_loss,
            loss_limit_amount=loss_limit,
            status=status,
            kill_switch_activated=False,
            checked_at=datetime.now(timezone.utc),
        )
        AccountDailyLossRepository(self._session).upsert_from_snapshot(
            snap,
            market_code=(
                "UPBIT" if broker_code == "UPBIT" else "KRX"
            ),
        )
        emit_live_safety_audit(
            self._session,
            event_type="UBA_DAILY_LOSS_RECALCULATED",
            actor=actor,
            run_id=after.correlation_id,
            user_id=None,
            account_id=uba_id,
            strategy_id=None,
            detail={
                "before": before.to_dict(),
                "after": after.to_dict(),
                "status": status.value,
            },
            commit=False,
        )
        if after.current_daily_loss < loss_limit:
            from stock_platform.risk_engine.kill_switch_service import (
                KillSwitchService,
            )
            from stock_platform.trading.account_identity import (
                uba_kill_switch_scope,
            )

            KillSwitchService(self._session).deactivate_scope(
                scope_code=uba_kill_switch_scope(uba_id),
                actor=actor,
                reason=(
                    "Daily loss recalculated below limit; "
                    "lifetime broker PnL was not daily"
                ),
            )
        self._session.commit()
        return after

    def _get_baseline(
        self, uba_id: int, day: date
    ) -> UbaDailyEquityBaselineEntity | None:
        return self._session.scalar(
            select(UbaDailyEquityBaselineEntity).where(
                UbaDailyEquityBaselineEntity.user_broker_account_id == uba_id,
                UbaDailyEquityBaselineEntity.trading_date == day,
                UbaDailyEquityBaselineEntity.currency_code == "KRW",
            )
        )

    def _execution_stats(self, uba_id: int, day: date) -> dict[str, int]:
        """당일 UBA 주문 건수 — FILLED 계열만 체결로 집계."""

        from datetime import timedelta

        day_start = datetime(
            day.year, day.month, day.day, tzinfo=_KST
        ).astimezone(timezone.utc)
        day_end = day_start + timedelta(days=1)
        rows = list(
            self._session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id == uba_id,
                    TradingOrderEntity.created_at >= day_start,
                    TradingOrderEntity.created_at < day_end,
                )
            )
        )
        buy = 0
        sell = 0
        filled_statuses = {
            "FILLED",
            "PARTIALLY_FILLED",
            "DONE",
            "COMPLETED",
        }
        total_filled = 0
        for row in rows:
            status = str(getattr(row, "status_code", "") or "").upper()
            if status in {
                "CANCELLED",
                "REJECTED",
                "EXPIRED",
                "CREATED",
                "PENDING",
            }:
                continue
            if status not in filled_statuses and status not in {
                "SENT",
                "ACCEPTED",
            }:
                if status not in filled_statuses:
                    continue
            if status in filled_statuses:
                total_filled += 1
                side = str(getattr(row, "side_code", "") or "").upper()
                if side == "BUY":
                    buy += 1
                elif side == "SELL":
                    sell += 1
        return {"total": total_filled, "buy": buy, "sell": sell}


__all__ = [
    "UbaDailyLossBreakdown",
    "UbaDailyLossService",
    "snapshot_equity",
    "snapshot_equity_detail",
    "daily_loss_from_pnl",
    "KIWOOM_EQUITY_V1_IMMEDIATE_CASH",
    "KIWOOM_EQUITY_V2_SETTLEMENT_AWARE",
]
