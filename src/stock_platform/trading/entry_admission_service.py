# -*- coding: utf-8 -*-
"""AUTO 신규 BUY 공통 Entry Admission (intent 생성 전).

최종 LiveOrderSafetyPipeline 은 유지한다 — 본 모듈은 upstream suppress 전용.
SELL / protective exit 에는 호출하지 말 것.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.live_open_order_exposure import (
    STATE_NOT_APPLICABLE,
    RemoteOpenOrderView,
    evaluate_live_open_order_exposure,
)
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicyResolver
from stock_platform.risk_engine.strategy_daily_loss_entry_gate import (
    resolve_canonical_strategy_id,
    should_suppress_auto_buy_for_daily_loss,
    trading_date_kst,
)

KST = ZoneInfo("Asia/Seoul")

# Telegram: (uba, day, reason) 최초 1회
_ADMISSION_TG: set[tuple[int, str, str]] = set()
_ADMISSION_TG_LOCK = Lock()

# actionable ambiguous — FILLED+stale ambiguous_since 제외
_ACTIVE_AMBIGUOUS_STATUSES = frozenset(
    {
        "AMBIGUOUS_SUBMISSION",
        "REMOTE_LOOKUP_PENDING",
        "IDENTITY_CONFLICT",
        "MANUAL_REVIEW_REQUIRED",
    }
)


@dataclass(frozen=True, slots=True)
class EntryAdmissionDecision:
    allowed: bool
    reason_code: str
    source: str
    strategy_id: int | None = None
    user_broker_account_id: int | None = None
    snapshot: dict[str, Any] = field(default_factory=dict)
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "source": self.source,
            "strategy_id": self.strategy_id,
            "user_broker_account_id": self.user_broker_account_id,
            "snapshot": self.snapshot,
            "checked_at": self.checked_at,
        }


def should_emit_admission_telegram(
    *,
    user_broker_account_id: int,
    reason_code: str,
    trading_day: date | None = None,
) -> bool:
    """persistent admission deny — KST day+UBA+reason 당 1회."""

    day = trading_day or trading_date_kst()
    key = (int(user_broker_account_id), day.isoformat(), str(reason_code))
    with _ADMISSION_TG_LOCK:
        if key in _ADMISSION_TG:
            return False
        _ADMISSION_TG.add(key)
        return True


def reset_admission_telegram_dedupe_for_tests() -> None:
    with _ADMISSION_TG_LOCK:
        _ADMISSION_TG.clear()


def count_active_ambiguous_orders(
    session: Session, *, user_broker_account_id: int
) -> tuple[int, list[dict[str, Any]]]:
    """ACTIVE_ACTIONABLE ambiguous 만. FILLED 등 terminal+stale 제외."""

    rows = list(
        session.scalars(
            select(TradingOrderEntity).where(
                TradingOrderEntity.user_broker_account_id
                == int(user_broker_account_id),
                TradingOrderEntity.ambiguous_since.is_not(None),
                TradingOrderEntity.status_code.in_(
                    tuple(_ACTIVE_AMBIGUOUS_STATUSES)
                ),
            )
        )
    )
    detail = [
        {
            "order_id": int(r.order_id),
            "symbol": r.symbol,
            "status_code": r.status_code,
            "classification": "ACTIVE_ACTIONABLE",
        }
        for r in rows
    ]
    return len(detail), detail


def count_active_recovery_conflicts(
    session: Session, *, user_broker_account_id: int
) -> int:
    """actionable recovery conflict 건수."""

    from sqlalchemy import func

    from stock_platform.broker.recovery_conflict_constants import (
        ACTIVE_REVIEW_STATUSES,
    )
    from stock_platform.broker.recovery_conflict_entities import (
        BrokerRecoveryConflictEntity,
    )

    return int(
        session.scalar(
            select(func.count())
            .select_from(BrokerRecoveryConflictEntity)
            .where(
                BrokerRecoveryConflictEntity.user_broker_account_id
                == int(user_broker_account_id),
                BrokerRecoveryConflictEntity.review_status.in_(
                    tuple(ACTIVE_REVIEW_STATUSES)
                ),
            )
        )
        or 0
    )


def classify_stale_ambiguous_sample(
    session: Session, *, user_broker_account_id: int, limit: int = 5
) -> list[dict[str, Any]]:
    """증거용 — ambiguous_since 있으나 terminal 인 건 STALE_HISTORICAL."""

    rows = list(
        session.scalars(
            select(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id
                == int(user_broker_account_id),
                TradingOrderEntity.ambiguous_since.is_not(None),
                TradingOrderEntity.status_code.notin_(
                    tuple(_ACTIVE_AMBIGUOUS_STATUSES)
                ),
            )
            .limit(limit)
        )
    )
    return [
        {
            "order_id": int(r.order_id),
            "symbol": r.symbol,
            "status_code": r.status_code,
            "classification": "STALE_HISTORICAL",
        }
        for r in rows
    ]


class EntryAdmissionService:
    """AUTO BUY common admission — intent 생성 전."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def evaluate_auto_buy(
        self,
        *,
        user_id: int | None,
        user_broker_account_id: int,
        broker_code: str,
        symbol: str,
        strategy_id: int | str | None,
        strategy_deployment_id: int | None = None,
        environment: str = "LIVE",
    ) -> EntryAdmissionDecision:
        now = datetime.now(KST).isoformat()
        uba = int(user_broker_account_id)
        broker = str(broker_code or "").upper()
        sym = str(symbol or "").strip().upper()
        sid = resolve_canonical_strategy_id(strategy_id=strategy_id)
        base_snap: dict[str, Any] = {
            "broker_code": broker,
            "symbol": sym,
            "environment": environment,
        }

        def _deny(reason: str, source: str, extra: dict[str, Any] | None = None) -> EntryAdmissionDecision:
            snap = {**base_snap, **(extra or {})}
            return EntryAdmissionDecision(
                allowed=False,
                reason_code=reason,
                source=source,
                strategy_id=sid,
                user_broker_account_id=uba,
                snapshot=snap,
                checked_at=now,
            )

        def _allow(source: str, extra: dict[str, Any] | None = None) -> EntryAdmissionDecision:
            return EntryAdmissionDecision(
                allowed=True,
                reason_code="ADMISSION_ALLOWED",
                source=source,
                strategy_id=sid,
                user_broker_account_id=uba,
                snapshot={**base_snap, **(extra or {})},
                checked_at=now,
            )

        if str(environment or "").upper() != "LIVE":
            return _allow("NOT_LIVE")

        # --- runtime / account safety ---
        from stock_platform.trading.account_models import UserBrokerAccount

        account = self._session.get(UserBrokerAccount, uba)
        if account is None:
            return _deny("ACCOUNT_NOT_FOUND", "RUNTIME")
        if not bool(getattr(account, "is_active", True)):
            return _deny("ACCOUNT_INACTIVE", "RUNTIME")
        if user_id is not None and int(account.user_id) != int(user_id):
            return _deny("ACCOUNT_USER_MISMATCH", "RUNTIME")
        if not bool(getattr(account, "live_order_enabled", False)):
            return _deny("LIVE_ORDER_DISABLED", "RUNTIME")

        try:
            from stock_platform.trading.live_arm_service import LiveArmService

            ok_arm, arm_reason = LiveArmService(
                self._session
            ).validate_arm_authorization(
                uba,
                arm_token=None,
                require_token_challenge=False,
            )
            if not ok_arm:
                return _deny(str(arm_reason or "ARM_INVALID"), "RUNTIME")
        except Exception as exc:  # noqa: BLE001
            return _deny(
                "ARM_CHECK_FAILED",
                "RUNTIME",
                {"error": type(exc).__name__},
            )

        try:
            from stock_platform.trading.live_unattended_authorization_service import (
                LiveUnattendedAuthorizationService,
            )

            if not LiveUnattendedAuthorizationService(
                self._session
            ).is_entry_authorized(uba):
                return _deny("UNATTENDED_ENTRY_BLOCKED", "RUNTIME")
        except Exception as exc:  # noqa: BLE001
            return _deny(
                "AUTH_CHECK_FAILED",
                "RUNTIME",
                {"error": type(exc).__name__},
            )

        try:
            from stock_platform.broker.live_transition_guard import (
                LiveTradingTransitionGuard,
            )

            LiveTradingTransitionGuard(self._session).require_active(
                user_broker_account_id=uba
            )
        except Exception as exc:  # noqa: BLE001
            return _deny(
                "ACTIVATION_INACTIVE",
                "RUNTIME",
                {"error": type(exc).__name__},
            )

        try:
            from stock_platform.risk_engine.kill_switch_guard import (
                PersistentKillSwitchGuard,
            )

            PersistentKillSwitchGuard(self._session).require_order_allowed(
                side="BUY",
                allow_sell=True,
                user_broker_account_id=uba,
            )
        except Exception as exc:  # noqa: BLE001
            reason = "KILL_SWITCH_ACTIVE"
            if "fail-closed" in str(exc).lower() or type(exc).__name__ == (
                "KillSwitchUnavailableError"
            ):
                reason = "KILL_SWITCH_CHECK_FAILED"
            return _deny(
                reason,
                "RUNTIME",
                {"error": type(exc).__name__},
            )

        # policy pause / buy disabled
        try:
            uid = int(user_id) if user_id is not None else int(account.user_id)
            policy = ResolvedRiskPolicyResolver(self._session).resolve(
                user_id=uid, user_broker_account_id=uba
            )
        except Exception as exc:  # noqa: BLE001
            return _deny(
                "RISK_CONFIG_INVALID",
                "RUNTIME",
                {"error": type(exc).__name__},
            )

        if bool(getattr(policy, "account_paused", False)):
            return _deny("ACCOUNT_PAUSED", "RUNTIME")
        if hasattr(policy, "buy_enabled") and not bool(policy.buy_enabled):
            return _deny("BUY_DISABLED", "RUNTIME")

        # --- strategy identity (AUTO) ---
        if sid is None:
            return _deny(
                "STRATEGY_IDENTITY_INVALID",
                "STRATEGY_IDENTITY",
                {"strategy_id_raw": strategy_id},
            )

        # --- daily loss (a8b0b4b reuse) ---
        suppress, dl_detail = should_suppress_auto_buy_for_daily_loss(
            self._session,
            user_broker_account_id=uba,
            broker_code=broker,
            strategy_id=sid,
            deployment_id=strategy_deployment_id,
            limit=Decimal(str(policy.daily_max_loss_amount)),
        )
        if suppress:
            return _deny(
                str(dl_detail.get("reason_code") or "DAILY_LOSS_LIMIT_REACHED"),
                "DAILY_LOSS",
                {"daily_loss": dl_detail},
            )

        # --- open order limit (local admission; final gate re-checks remote) ---
        try:
            exposure = evaluate_live_open_order_exposure(
                self._session,
                uba_id=uba,
                broker_code=broker,
                environment="LIVE",
                remote_view=RemoteOpenOrderView(
                    status=STATE_NOT_APPLICABLE,
                    source="ADMISSION_LOCAL_PRECHECK",
                ),
            )
            max_open = int(policy.max_open_orders)
            auto_open = int(exposure.auto_open_count)
            if int(exposure.unknown_open_count) > 0:
                return _deny(
                    "ORDER_OWNERSHIP_UNKNOWN",
                    "OPEN_ORDER",
                    {"exposure": exposure.as_detail(), "max_open_orders": max_open},
                )
            if auto_open >= max_open:
                return _deny(
                    "OPEN_ORDER_LIMIT_REACHED",
                    "OPEN_ORDER",
                    {
                        "exposure": exposure.as_detail(),
                        "max_open_orders": max_open,
                        "canonical_active_count": auto_open,
                    },
                )
        except Exception as exc:  # noqa: BLE001
            return _deny(
                "OPEN_ORDER_CHECK_FAILED",
                "OPEN_ORDER",
                {"error": type(exc).__name__},
            )

        # --- position / AUTO slot limit ---
        try:
            from stock_platform.operation.upbit_full_market.auto_slot_count import (
                count_auto_slots_used,
            )

            used = int(
                count_auto_slots_used(
                    self._session,
                    user_broker_account_id=uba,
                    broker_code=broker,
                )
            )
            # ResolvedRiskPolicy: max_position_count (engine: max_open_positions)
            max_pos = int(getattr(policy, "max_position_count", 0) or 0)
            if max_pos > 0 and used >= max_pos:
                return _deny(
                    "AUTO_POSITION_LIMIT_REACHED",
                    "POSITION_LIMIT",
                    {
                        "slots_used": used,
                        "max_position_count": max_pos,
                    },
                )
        except Exception as exc:  # noqa: BLE001
            return _deny(
                "POSITION_LIMIT_CHECK_FAILED",
                "POSITION_LIMIT",
                {"error": type(exc).__name__},
            )

        # --- managed symbol / ownership (e6edf9d) ---
        try:
            from stock_platform.trading.symbol_ownership import (
                SymbolOwnershipService,
            )

            allowed, skip_reason, ownership = SymbolOwnershipService(
                self._session
            ).entry_gate(
                broker_code=broker,
                user_broker_account_id=uba,
                symbol=sym,
            )
            own_dict = (
                ownership.to_dict() if hasattr(ownership, "to_dict") else {}
            )
            if not allowed:
                return _deny(
                    str(skip_reason or "SYMBOL_OWNERSHIP_BLOCKED"),
                    "MANAGED_SYMBOL",
                    {"ownership": own_dict},
                )
        except Exception as exc:  # noqa: BLE001
            return _deny(
                "SYMBOL_OWNERSHIP_UNKNOWN",
                "MANAGED_SYMBOL",
                {"error": type(exc).__name__},
            )

        # --- active ambiguous / recovery ---
        amb_n, amb_rows = count_active_ambiguous_orders(
            self._session, user_broker_account_id=uba
        )
        if amb_n > 0:
            return _deny(
                "AMBIGUOUS_ORDER_ACTIVE",
                "AMBIGUOUS_RECOVERY",
                {"active_ambiguous": amb_rows},
            )

        try:
            conflict_n = count_active_recovery_conflicts(
                self._session, user_broker_account_id=uba
            )
            if conflict_n > 0:
                return _deny(
                    "RECOVERY_CONFLICT_ACTIVE",
                    "AMBIGUOUS_RECOVERY",
                    {"recovery_conflicts": conflict_n},
                )
        except Exception:
            # 조회 실패 시 skip — final gate 가 보호
            pass

        # portfolio daily entry (precheck; atomic final admit 는 persist 직전 유지)
        try:
            from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
                MODE_LIMITED,
                resolve_portfolio_daily_entry_policy,
            )
            from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
                count_portfolio_daily_real_entries,
            )

            mode, limit = resolve_portfolio_daily_entry_policy(
                self._session, uba
            )
            if mode == MODE_LIMITED and limit is not None:
                used_entries = int(
                    count_portfolio_daily_real_entries(
                        self._session, user_broker_account_id=uba
                    )
                )
                if used_entries >= int(limit):
                    return _deny(
                        "DAILY_ENTRY_LIMIT_REACHED",
                        "DAILY_ENTRY",
                        {
                            "used": used_entries,
                            "limit": int(limit),
                            "mode": mode,
                        },
                    )
        except Exception:
            pass

        return _allow(
            "ENTRY_ADMISSION",
            {
                "strategy_id": sid,
                "max_open_orders": int(policy.max_open_orders),
                "daily_max_loss_amount": str(policy.daily_max_loss_amount),
            },
        )
