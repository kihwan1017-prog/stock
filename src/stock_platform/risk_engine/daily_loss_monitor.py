from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
)
from stock_platform.risk_engine.alert import (
    LoggingRiskAlertNotifier,
    RiskAlertNotifier,
)
from stock_platform.risk_engine.daily_loss_models import (
    DailyLossMonitorStatus,
    DailyLossSnapshot,
)
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)
from stock_platform.risk_engine.risk_event_repository import (
    RiskEventRepository,
)
from stock_platform.trading.account_identity import (
    AccountIdentityError,
    AccountIdentityErrorCode,
    uba_kill_switch_scope,
)
from stock_platform.trading.account_masking import mask_account_number


ZERO = Decimal("0")
_KST = ZoneInfo("Asia/Seoul")


class DailyLossMonitor:
    """STEP 8-5-18 — ACTIVE Snapshot 을 UBA 기준으로만 집계."""

    def __init__(
        self,
        *,
        session: Session,
        loss_limit: Decimal,
        notifier: RiskAlertNotifier | None = None,
    ) -> None:
        if loss_limit <= ZERO:
            raise ValueError("loss_limit must be greater than zero")

        self._session = session
        self._loss_limit = loss_limit
        self._notifier = notifier or LoggingRiskAlertNotifier()
        self._kill_switch = KillSwitchService(session)
        self._events = RiskEventRepository(session)
        self._snapshots = BrokerAccountSnapshotRepository(session)

    async def check_uba(
        self,
        *,
        user_broker_account_id: int,
        currency: str = "KRW",
        trading_date: date | None = None,
    ) -> DailyLossSnapshot:
        uba_id = int(user_broker_account_id)
        account, positions = self._snapshots.get_active_by_uba(uba_id)
        if account is None:
            raise LookupError(
                "Broker account snapshot not found for UBA"
            )

        day = trading_date or datetime.now(_KST).date()
        from stock_platform.risk_engine.uba_daily_loss_service import (
            UbaDailyLossService,
            snapshot_equity,
        )

        loss_svc = UbaDailyLossService(self._session)
        broker_code = str(account.broker_code).upper()
        # 기존 baseline이 있으면 그 policy로 equity 계산 (mid-day mixing 금지)
        existing_baseline = loss_svc._get_baseline(uba_id, day)
        policy = loss_svc.resolve_equity_policy(
            broker_code=broker_code,
            baseline=existing_baseline,
            for_new_baseline=existing_baseline is None,
        )
        equity = snapshot_equity(account, policy_version=policy)
        loss_svc.ensure_baseline(
            user_broker_account_id=uba_id,
            opening_equity=equity,
            trading_date=day,
            source_code="FIRST_OBSERVED",
            actor="SYSTEM_DAILY_LOSS_MONITOR",
            broker_code=broker_code,
            force_replace=False,
            equity_policy_version=policy,
        )
        breakdown = loss_svc.diagnose(
            user_broker_account_id=uba_id,
            loss_limit=self._loss_limit,
            trading_date=day,
        )
        realized = breakdown.realized_pnl
        unrealized = breakdown.unrealized_pnl
        combined = breakdown.current_daily_pnl
        current_loss = breakdown.current_daily_loss
        masked = mask_account_number(account.account_number)
        scope = uba_kill_switch_scope(uba_id)
        _ = positions  # lifetime position pnl 미사용 (이중합산 금지)

        kill_switch_was_active = self._kill_switch.is_active_for_scopes(
            [KillSwitchService.GLOBAL_SCOPE, scope]
        )
        activated = False

        if current_loss >= self._loss_limit:
            # Account MTM telemetry — Strategy ENTRY는 strategy-owned PnL 게이트 사용.
            # 계좌 전체 MTM만으로 Kill을 자동 켜지 않는다 (2-layer Risk).
            status = (
                DailyLossMonitorStatus.KILL_SWITCH_ACTIVE
                if kill_switch_was_active
                else DailyLossMonitorStatus.LIMIT_REACHED
            )
            detail = {
                "event_type": "ACCOUNT_DAILY_DRAWDOWN",
                "broker_code": broker_code,
                "user_broker_account_id": uba_id,
                "masked_account_ref": masked,
                "trading_date": day.isoformat(),
                "currency": currency.upper(),
                "realized_profit_loss": str(realized),
                "unrealized_profit_loss": str(unrealized),
                "combined_profit_loss": str(combined),
                "current_loss_amount": str(current_loss),
                "loss_limit_amount": str(self._loss_limit),
                "equity_policy_version": breakdown.equity_policy_version,
                "equity_source": breakdown.equity_source,
                "pending_settlement_cash": breakdown.pending_settlement_cash,
                "auto_kill": False,
                "note": (
                    "Account drawdown telemetry only; "
                    "Kill not auto-activated"
                ),
            }
            self._events.create(
                event_type="ACCOUNT_DAILY_DRAWDOWN",
                event_level="WARNING",
                broker_code=broker_code,
                user_broker_account_id=uba_id,
                masked_account_ref=masked,
                correlation_id=f"account-drawdown-uba-{uba_id}-{day.isoformat()}",
                current_loss_amount=current_loss,
                loss_limit_amount=self._loss_limit,
                message=(
                    "Account daily drawdown telemetry: "
                    f"{current_loss} >= {self._loss_limit}, "
                    f"BROKER={broker_code}, UBA={uba_id}, "
                    f"ACCOUNT={masked}"
                ),
                detail_payload=detail,
            )
            await self._notifier.send(
                title="계좌 손실 현황",
                message=(
                    "계좌 전체 평가손실이 알림 기준을 초과했습니다. "
                    "Kill Switch는 자동 작동하지 않았습니다."
                ),
                detail=detail,
            )
        else:
            status = DailyLossMonitorStatus.SAFE

        result = DailyLossSnapshot(
            user_broker_account_id=uba_id,
            paper_account_id=None,
            broker_code=broker_code,
            masked_account_ref=masked,
            trading_date=day.isoformat(),
            currency=currency.upper(),
            realized_profit_loss=realized,
            unrealized_profit_loss=unrealized,
            combined_profit_loss=combined,
            current_loss_amount=current_loss,
            loss_limit_amount=self._loss_limit,
            status=status,
            kill_switch_activated=activated,
            checked_at=datetime.now(timezone.utc),
        )
        from stock_platform.risk_engine.daily_loss_repository import (
            AccountDailyLossRepository,
        )

        AccountDailyLossRepository(self._session).upsert_from_snapshot(
            result,
            market_code=broker_code if broker_code == "UPBIT" else "KRX",
        )
        return result

    async def check_paper(
        self,
        *,
        paper_account_id: int,
        currency: str = "KRW",
        trading_date: date | None = None,
        market_code: str = "KRX",
    ) -> DailyLossSnapshot:
        """Paper 계좌 Daily Loss — PaperAccount 잔고/실현손익 기준."""

        from stock_platform.trading.account_identity import (
            paper_kill_switch_scope,
        )
        from stock_platform.trading.account_models import (
            PaperAccount,
            PaperPosition,
        )
        from sqlalchemy import select

        paper_id = int(paper_account_id)
        account = self._session.get(PaperAccount, paper_id)
        if account is None:
            raise LookupError(f"Paper account not found: {paper_id}")

        day = trading_date or datetime.now(_KST).date()
        realized = Decimal(account.realized_profit_loss or ZERO)
        positions = list(
            self._session.scalars(
                select(PaperPosition).where(
                    PaperPosition.account_id == paper_id,
                    PaperPosition.quantity > 0,
                )
            )
        )
        unrealized = ZERO
        for item in positions:
            # avg/current 미보관 시 0 — 실현손익 중심
            unrealized += Decimal(getattr(item, "unrealized_pnl", ZERO) or ZERO)
        combined = realized + unrealized
        current_loss = max(-combined, ZERO)
        scope = paper_kill_switch_scope(paper_id)
        kill_switch_was_active = self._kill_switch.is_active_for_scopes(
            [KillSwitchService.GLOBAL_SCOPE, scope]
        )
        activated = False
        if current_loss >= self._loss_limit:
            status = (
                DailyLossMonitorStatus.KILL_SWITCH_ACTIVE
                if kill_switch_was_active
                else DailyLossMonitorStatus.LIMIT_REACHED
            )
            if not kill_switch_was_active:
                reason = (
                    "Paper daily loss limit reached: "
                    f"{current_loss} >= {self._loss_limit}, "
                    f"PAPER={paper_id}"
                )
                self._kill_switch.activate_scope(
                    scope_code=scope,
                    actor="SYSTEM_DAILY_LOSS_MONITOR",
                    reason=reason,
                )
                activated = True
                self._events.create(
                    event_type="AUTO_KILL_SWITCH",
                    event_level="CRITICAL",
                    broker_code="PAPER",
                    paper_account_id=paper_id,
                    masked_account_ref=f"PAPER:{paper_id}",
                    correlation_id=(
                        f"daily-loss-paper-{paper_id}-{day.isoformat()}"
                    ),
                    current_loss_amount=current_loss,
                    loss_limit_amount=self._loss_limit,
                    message=reason,
                    detail_payload={
                        "event_type": "DAILY_LOSS",
                        "paper_account_id": paper_id,
                        "trading_date": day.isoformat(),
                        "currency": currency.upper(),
                    },
                )
        else:
            status = DailyLossMonitorStatus.SAFE

        result = DailyLossSnapshot(
            user_broker_account_id=None,
            paper_account_id=paper_id,
            broker_code="PAPER",
            masked_account_ref=f"PAPER:{paper_id}",
            trading_date=day.isoformat(),
            currency=currency.upper(),
            realized_profit_loss=realized,
            unrealized_profit_loss=unrealized,
            combined_profit_loss=combined,
            current_loss_amount=current_loss,
            loss_limit_amount=self._loss_limit,
            status=status,
            kill_switch_activated=activated,
            checked_at=datetime.now(timezone.utc),
        )
        from stock_platform.risk_engine.daily_loss_repository import (
            AccountDailyLossRepository,
        )

        AccountDailyLossRepository(self._session).upsert_from_snapshot(
            result,
            market_code=market_code,
        )
        return result

    async def check(
        self,
        *,
        broker_code: str | None = None,
        account_number: str | None = None,
        user_broker_account_id: int | None = None,
        paper_account_id: int | None = None,
    ) -> DailyLossSnapshot:
        """호환 Wrapper — UBA 또는 Paper 필수. account_number-only 거부."""

        if user_broker_account_id is not None:
            return await self.check_uba(
                user_broker_account_id=int(user_broker_account_id),
            )
        if paper_account_id is not None:
            return await self.check_paper(
                paper_account_id=int(paper_account_id),
            )
        raise AccountIdentityError(
            AccountIdentityErrorCode.LEGACY_ACCOUNT_NUMBER_ONLY
            if account_number
            else AccountIdentityErrorCode.UBA_REQUIRED,
            "DailyLossMonitor requires user_broker_account_id "
            f"or paper_account_id"
            f"{f', broker={broker_code}' if broker_code else ''}",
        )

    def reset_daily_state(
        self,
        *,
        actor: str,
        reason: str,
    ) -> dict:
        state = self._kill_switch.get_state()
        return {
            "reset": True,
            "kill_switch_status": state.status.value,
            "message": (
                "Daily monitor has no independent loss "
                "counter. Account snapshots are the source."
            ),
            "actor": actor,
            "reason": reason,
        }
