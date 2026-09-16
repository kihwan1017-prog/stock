"""Runtime 제어 공통 Gate 헬퍼 — LIVE/ARM/Scheduler 사전조건 공유."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable
from unittest.mock import MagicMock

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.risk_engine.resolved_policy import (
    ResolvedRiskPolicyResolver,
)
from stock_platform.trading.account_models import UserBrokerAccount

# Recovery 정상으로 인정하는 상태 (Resume 완료 후)
_OK_RECOVERY = frozenset({"SUCCESS", "READY", "IDLE", ""})


def assert_uba_connection_ready(
    uba: UserBrokerAccount,
    *,
    raise_error: Callable[[str, str], Exception],
) -> None:
    """connection_status 가 CONNECTED/VERIFIED 인지 검사."""
    conn = str(getattr(uba, "connection_status", "") or "").upper()
    if conn not in {"CONNECTED", "VERIFIED"}:
        raise raise_error(
            "connection_not_connected",
            f"connection_status must be CONNECTED (actual={conn or 'EMPTY'})",
        )


def assert_recovery_ready(
    session: Session,
    uba_id: int,
    *,
    raise_error: Callable[[str, str], Exception],
) -> dict[str, Any]:
    """trading_paused=false 및 recovery_status 정상 여부."""
    state = session.scalar(
        select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id
            == int(uba_id)
        )
    )
    if state is not None and bool(state.trading_paused):
        raise raise_error(
            "trading_paused", "Account trading is paused"
        )
    recovery_status = (
        str(getattr(state, "recovery_status", None) or "").upper()
        if state
        else ""
    )
    if recovery_status and recovery_status not in _OK_RECOVERY:
        if recovery_status in {"MANUAL_REVIEW", "RUNNING", "FAILED"}:
            raise raise_error(
                "recovery_not_ready",
                f"recovery_status must be SUCCESS/READY "
                f"(actual={recovery_status})",
            )
    return {
        "trading_paused": bool(getattr(state, "trading_paused", False))
        if state
        else False,
        "recovery_status": getattr(state, "recovery_status", None)
        if state
        else None,
    }


def assert_risk_account_not_paused(
    session: Session,
    uba: UserBrokerAccount,
    *,
    raise_error: Callable[[str, str], Exception],
) -> dict[str, Any]:
    """Risk account_paused=false 및 기본 한도 유효성."""
    policy = ResolvedRiskPolicyResolver(session).resolve(
        user_id=int(uba.user_id),
        user_broker_account_id=int(uba.user_broker_account_id),
    )
    paused = getattr(policy, "account_paused", False)
    if isinstance(paused, bool) and paused:
        raise raise_error(
            "account_paused",
            "Risk account_paused is true — LIVE/ARM/Scheduler blocked",
        )
    for attr in (
        "max_order_amount",
        "max_order_quantity",
        "daily_order_limit",
        "daily_max_loss_amount",
    ):
        raw = getattr(policy, attr, None)
        if raw is None or isinstance(raw, MagicMock):
            continue
        if not isinstance(raw, (int, float, str, Decimal)):
            continue
        try:
            if float(raw) < 0:
                raise raise_error(
                    "risk_limit_invalid",
                    f"Risk {attr} is invalid: {raw}",
                )
        except (TypeError, ValueError) as exc:
            raise raise_error(
                "risk_limit_invalid",
                f"Risk {attr} is invalid: {raw}",
            ) from exc
    ttl_raw = getattr(policy, "arm_ttl_seconds", 300)
    ttl = (
        int(ttl_raw)
        if isinstance(ttl_raw, (int, float)) and not isinstance(ttl_raw, bool)
        else 300
    )
    return {
        "account_paused": False,
        "arm_ttl_seconds": ttl,
    }
