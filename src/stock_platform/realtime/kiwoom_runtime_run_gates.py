"""KIWOOM LIVE 주문 직전 run gate — UPBIT pause/mutation 없음.

Activation/LIVE/ARM/Kill/Pause/Recovery/Connection/Credential/Worker
를 읽기 전용으로 검사한다. expire/commit/LIVE OFF 없음.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.runtime_control_gates import (
    assert_recovery_ready,
    assert_risk_account_not_paused,
    assert_uba_connection_ready,
)
from stock_platform.trading.upbit_24x7_control import (
    REASON_ACCOUNT_PAUSED,
    REASON_ACTIVATION_INACTIVE,
    REASON_ARM_EXPIRED,
    REASON_CONNECTION_NOT_READY,
    REASON_CREDENTIAL_INVALID,
    REASON_KILL_SWITCH_ACTIVE,
    REASON_LIVE_OFF,
    REASON_RECOVERY_NOT_READY,
    REASON_TRADING_PAUSED,
    REASON_UBA_BROKER_MISMATCH,
    REASON_UBA_INACTIVE,
    _arm_effective,
    _credential_verified,
    live_outbox_queue_block_reason,
)


REASON_UNSUPPORTED_BROKER = "UNSUPPORTED_BROKER"


def _raise_error(code: str, message: str) -> Exception:
    from stock_platform.trading.upbit_24x7_control import (
        Upbit24x7ControlError,
    )

    return Upbit24x7ControlError(code, message)


def _kill_active_kiwoom(session: Session) -> bool:
    from stock_platform.risk_engine.kill_switch_service import KillSwitchService

    svc = KillSwitchService(session)
    if svc.is_active():
        return True
    return svc.is_active_for_scopes(["KIWOOM", "GLOBAL"])


def _activation_active_kiwoom(
    session: Session,
    uba_id: int,
) -> dict[str, Any]:
    """peek만 사용. expire/commit 없음."""

    from stock_platform.broker.live_transition_service import (
        LiveTradingTransitionService,
    )

    entity = LiveTradingTransitionService(session).peek_active(
        broker_code="KIWOOM",
        user_broker_account_id=int(uba_id),
    )
    if entity is None:
        return {"ok": False}
    return {
        "ok": True,
        "activation_status": getattr(entity, "activation_status", None),
        "transition_id": getattr(entity, "live_trading_transition_id", None),
    }


def evaluate_kiwoom_runtime_run_gates(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int | None = None,
    tick_source_code: str | None = None,
) -> dict[str, Any]:
    """KIWOOM 주문 직전 fail-closed. UPBIT runtime pause를 호출하지 않는다."""

    checks: dict[str, Any] = {
        "broker": "KIWOOM",
        "mutates_upbit": False,
        "runtime_paused": False,
    }
    blockers: list[str] = []
    uba_id = int(user_broker_account_id)

    uba = session.get(UserBrokerAccount, uba_id)
    if uba is None or not bool(uba.is_active) or getattr(uba, "deleted_at", None):
        blockers.append(REASON_UBA_INACTIVE)
        return {"ok": False, "blockers": blockers, "checks": checks}

    broker = str(uba.broker_code or "").upper()
    checks["uba"] = {
        "user_broker_account_id": uba_id,
        "broker_code": broker,
        "is_active": True,
    }
    if broker != "KIWOOM":
        blockers.append(REASON_UBA_BROKER_MISMATCH)

    try:
        assert_uba_connection_ready(uba, raise_error=_raise_error)
        checks["connection"] = {"ok": True, "status": uba.connection_status}
    except Exception:  # noqa: BLE001
        blockers.append(REASON_CONNECTION_NOT_READY)
        checks["connection"] = {
            "ok": False,
            "status": getattr(uba, "connection_status", None),
        }

    cred_ok, cred_status = _credential_verified(session, uba_id)
    checks["credential"] = {"ok": cred_ok, "verification_status": cred_status}
    if not cred_ok:
        blockers.append(REASON_CREDENTIAL_INVALID)

    try:
        rec = assert_recovery_ready(session, uba_id, raise_error=_raise_error)
        checks["recovery"] = {"ok": True, **rec}
    except Exception as exc:  # noqa: BLE001
        code = (
            REASON_TRADING_PAUSED
            if getattr(exc, "code", "") == "trading_paused"
            else REASON_RECOVERY_NOT_READY
        )
        blockers.append(code)
        checks["recovery"] = {"ok": False, "code": getattr(exc, "code", None)}

    try:
        risk = assert_risk_account_not_paused(
            session, uba, raise_error=_raise_error
        )
        checks["account_paused"] = {"ok": True, **risk}
    except Exception:  # noqa: BLE001
        blockers.append(REASON_ACCOUNT_PAUSED)
        checks["account_paused"] = {"ok": False}

    kill_on = False
    try:
        kill_on = _kill_active_kiwoom(session)
    except Exception:  # noqa: BLE001
        kill_on = True
    checks["kill_switch"] = {"ok": not kill_on, "active": kill_on}
    if kill_on:
        blockers.append(REASON_KILL_SWITCH_ACTIVE)

    try:
        act = _activation_active_kiwoom(session, uba_id)
        checks["activation"] = act
        if not act.get("ok"):
            blockers.append(REASON_ACTIVATION_INACTIVE)
    except Exception:  # noqa: BLE001
        checks["activation"] = {"ok": False}
        blockers.append(REASON_ACTIVATION_INACTIVE)

    live_on = bool(getattr(uba, "live_order_enabled", False))
    checks["live"] = {"ok": live_on, "live_order_enabled": live_on}
    if not live_on:
        blockers.append(REASON_LIVE_OFF)

    from stock_platform.broker.live_config_gate import (
        evaluate_live_flag_consistency,
    )

    live_cfg = evaluate_live_flag_consistency(
        broker_code="KIWOOM",
        session=session,
        user_broker_account_id=uba_id,
    )
    checks["live_flag"] = {
        "code": live_cfg.code,
        "status": live_cfg.status,
        "allowed": live_cfg.allowed,
    }
    if live_cfg.code == "LIVE_MOCK_CONFLICT":
        blockers.append("LIVE_MOCK_CONFLICT")

    arm_ok, arm_detail = _arm_effective(uba)
    checks["arm"] = {"ok": arm_ok, **arm_detail}
    if not arm_ok:
        blockers.append(REASON_ARM_EXPIRED)

    if strategy_id is not None:
        checks["strategy_id"] = int(strategy_id)

    if tick_source_code is not None:
        from stock_platform.realtime.kiwoom_market_source_gate import (
            evaluate_real_execution_market_source,
        )

        market_src = evaluate_real_execution_market_source(
            session,
            user_broker_account_id=uba_id,
            broker_code="KIWOOM",
            source_code=tick_source_code,
        )
        checks["market_source"] = market_src
        if market_src.get("applied") and not market_src.get("ok"):
            blockers.append(
                str(market_src.get("reason") or "MARKET_SOURCE_BLOCKED")
            )

    worker_reason = live_outbox_queue_block_reason()
    from stock_platform.common.settings import get_settings
    from stock_platform.order.live_outbox_worker_runtime import (
        live_outbox_worker_runtime,
    )

    worker_status = live_outbox_worker_runtime.status()
    worker_running = worker_reason is None
    checks["outbox_worker"] = {
        "enabled": bool(worker_status.get("enabled")),
        "running": bool(worker_status.get("running")),
        "auto_start": bool(
            getattr(get_settings(), "live_outbox_worker_auto_start", False)
        ),
        "dispatch_allowed_if_running": False,
    }
    if (
        bool(getattr(get_settings(), "live_outbox_worker_enabled", False))
        and not worker_running
    ):
        from stock_platform.trading.upbit_24x7_control import (
            REASON_OUTBOX_WORKER_NOT_RUNNING,
        )

        blockers.append(REASON_OUTBOX_WORKER_NOT_RUNNING)

    _ = datetime.now(timezone.utc)
    return {
        "ok": not blockers,
        "blockers": blockers,
        "checks": checks,
        "runtime_paused": False,
    }
