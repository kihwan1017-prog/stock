"""UPBIT 24/7 Runtime · Outbox Worker · Exit Monitor 운영 제어 계약.

새 Runtime engine을 만들지 않는다. 기존 Scoped Runtime / LiveOutboxWorker /
Position Exit Monitor를 명시적 operator START/STOP으로 묶는다.

정책:
- AUTO Activation / AUTO LIVE / AUTO ARM 금지
- Worker auto_start 기본 false (operator-controlled START)
- Worker RUNNING ≠ broker CREATE 허용 (dispatch fail-closed 유지)
- Strategy Runtime과 Exit Monitor lifecycle 분리
- START ALL 없음
- Trading Scheduler는 UPBIT 24/7 필수 아님
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
)
from stock_platform.strategy_deployment.runtime_scope import (
    RuntimeLifecycleStatus,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.runtime_control_gates import (
    assert_recovery_ready,
    assert_risk_account_not_paused,
    assert_uba_connection_ready,
)


REASON_UBA_INACTIVE = "UBA_INACTIVE"
REASON_UBA_BROKER_MISMATCH = "UBA_BROKER_MISMATCH"
REASON_CREDENTIAL_INVALID = "CREDENTIAL_INVALID"
REASON_CONNECTION_NOT_READY = "CONNECTION_NOT_READY"
REASON_RECOVERY_NOT_READY = "RECOVERY_NOT_READY"
REASON_TRADING_PAUSED = "TRADING_PAUSED"
REASON_ACCOUNT_PAUSED = "ACCOUNT_PAUSED"
REASON_KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
REASON_ACTIVATION_INACTIVE = "ACTIVATION_INACTIVE"
REASON_LIVE_OFF = "LIVE_OFF"
REASON_ARM_EXPIRED = "ARM_EXPIRED"
REASON_STRATEGY_INACTIVE = "STRATEGY_INACTIVE"
REASON_STRATEGY_NOT_APPROVED = "STRATEGY_NOT_APPROVED"
REASON_STRATEGY_EVIDENCE_NOT_READY = "STRATEGY_EVIDENCE_NOT_READY"
REASON_RUNTIME_REGISTRATION_NOT_READY = "RUNTIME_REGISTRATION_NOT_READY"
REASON_OUTBOX_WORKER_NOT_RUNNING = "OUTBOX_WORKER_NOT_RUNNING"
REASON_WORKER_DISABLED = "LIVE_OUTBOX_WORKER_DISABLED"
REASON_CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
REASON_KIWOOM_ISOLATION = "KIWOOM_RUNTIME_START_FORBIDDEN"

CONFIRM_START_RUNTIME = "START RUNTIME"
CONFIRM_STOP_RUNTIME = "STOP RUNTIME"
CONFIRM_START_WORKER = "START OUTBOX WORKER"
CONFIRM_STOP_WORKER = "STOP OUTBOX WORKER"
CONFIRM_START_EXIT_MONITOR = "START EXIT MONITOR"
CONFIRM_STOP_EXIT_MONITOR = "STOP EXIT MONITOR"

# 운영 시작 순서 — source(Runtime)보다 Worker를 먼저 켠다.
OPERATING_START_SEQUENCE = (
    "ACCOUNT_ACTIVATION",
    "LIVE_ON",
    "ARM_ON",
    "OUTBOX_WORKER_START",
    "EXIT_MONITOR_ACTIVE",
    "STRATEGY_RUNTIME_START",
)

# 종료: ENTRY 먼저 끊고, 포지션 보호(Exit)는 Worker보다 늦게 끈다.
OPERATING_STOP_SEQUENCE = (
    "STRATEGY_RUNTIME_STOP",
    "CONFIRM_OUTSTANDING",
    "EXIT_MONITOR_STOP",
    "OUTBOX_WORKER_STOP",
    "ARM_OFF",
    "LIVE_OFF",
    "ACTIVATION_DISABLE",
)

# backend restart 후 복원 정책.
# LIVE/ARM은 현재 StartupPolicy가 FORCE OFF → REQUIRE_OPERATOR.
RESTART_POLICY: dict[str, str] = {
    "activation": "PERSIST",
    "live": "REQUIRE_OPERATOR",
    "arm": "REQUIRE_OPERATOR",
    "strategy_runtime": "STOP",
    "outbox_worker": "REQUIRE_OPERATOR",
    "exit_monitor": "AUTO_RESTORE",
    "session_expiry_runtime": "AUTO_RESTORE",
}

WORKER_AUTO_START_POLICY = "OPERATOR_CONTROLLED"
RESUME_AFTER_SAFETY_BREAK = "REQUIRE_OPERATOR"
UPBIT_MARKET_DATA_24X7 = "YES"


class Upbit24x7ControlError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _raise_error(code: str, message: str) -> Upbit24x7ControlError:
    return Upbit24x7ControlError(code, message)


def _require_confirmation(text: str, phrase: str) -> None:
    raw = (text or "").strip().upper()
    if phrase not in raw:
        raise Upbit24x7ControlError(
            REASON_CONFIRMATION_REQUIRED,
            f"confirmation_text must include '{phrase}'",
        )


def live_outbox_queue_block_reason() -> str | None:
    """LIVE TradingOrder/Outbox enqueue 직전 Worker 백프레셔.

    enabled=false 이면 기존 테스트·Paper 경로를 깨지 않는다.
    enabled=true 이고 running=false 이면 ENTRY/EXIT 모두 차단.
    """

    from stock_platform.common.settings import get_settings
    from stock_platform.order.live_outbox_worker_runtime import (
        live_outbox_worker_runtime,
    )

    settings = get_settings()
    if not bool(getattr(settings, "live_outbox_worker_enabled", False)):
        return None
    status = live_outbox_worker_runtime.status()
    if bool(status.get("running")):
        return None
    return REASON_OUTBOX_WORKER_NOT_RUNNING


def _kill_active(session: Session) -> bool:
    from stock_platform.risk_engine.kill_switch_service import KillSwitchService

    svc = KillSwitchService(session)
    if svc.is_active():
        return True
    return svc.is_active_for_scopes(["UPBIT", "GLOBAL"])


def _credential_verified(session: Session, uba_id: int) -> tuple[bool, str | None]:
    from stock_platform.broker.credential_vault_service import (
        BrokerCredentialVaultService,
    )

    view = BrokerCredentialVaultService(session).status(int(uba_id))
    status = str(getattr(view, "verification_status", None) or "").upper()
    if status == "VERIFIED":
        return True, status
    return False, status or None


def _activation_active(session: Session, uba_id: int) -> dict[str, Any]:
    """STATUS READ 전용 — peek만 사용. expire/commit/broker 호출 없음.

    UBA의 실제 broker_code로 Activation을 조회한다.
    (UPBIT 하드코딩 시 KIWOOM UBA가 항상 ACTIVATION_INACTIVE로 오탐됨)
    """

    from stock_platform.broker.live_transition_service import (
        LiveTradingTransitionService,
    )

    uba = session.get(UserBrokerAccount, int(uba_id))
    broker = (
        str(uba.broker_code or "").upper()
        if uba is not None
        else "UPBIT"
    ) or "UPBIT"
    entity = LiveTradingTransitionService(session).peek_active(
        broker_code=broker,
        user_broker_account_id=int(uba_id),
    )
    if entity is None:
        return {"ok": False, "broker_code": broker}
    return {
        "ok": True,
        "broker_code": broker,
        "activation_status": getattr(entity, "activation_status", None),
        "transition_id": getattr(entity, "live_trading_transition_id", None),
    }


def _arm_effective(uba: UserBrokerAccount) -> tuple[bool, dict[str, Any]]:
    now = _now()
    expires = getattr(uba, "arm_expires_at", None)
    armed = bool(getattr(uba, "live_armed", False))
    expired = False
    if expires is not None:
        exp = expires
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        expired = exp <= now
    effective = armed and not expired
    return effective, {
        "live_armed": armed,
        "expired": expired,
        "arm_expires_at": expires.isoformat() if expires is not None else None,
    }


def _strategy_ready(
    session: Session,
    *,
    uba_id: int,
    strategy_id: int,
) -> dict[str, Any]:
    from stock_platform.trading.strategy_runtime_authorization import (
        evaluate_strategy_runtime_authorization,
    )

    auth = evaluate_strategy_runtime_authorization(
        session, strategy_id=int(strategy_id)
    )
    if not auth.get("ok"):
        return {
            **auth,
            "approved": False,
        }

    link = session.scalar(
        select(AccountStrategyLinkEntity).where(
            AccountStrategyLinkEntity.user_broker_account_id == int(uba_id),
            AccountStrategyLinkEntity.strategy_id == int(strategy_id),
            AccountStrategyLinkEntity.is_active.is_(True),
        )
    )
    if link is None:
        return {
            "ok": False,
            "code": REASON_RUNTIME_REGISTRATION_NOT_READY,
            "approved": True,
        }

    registry_ok = True
    try:
        from stock_platform.ai.strategy_draft_approval.runtime_registration_entities import (
            StrategyRuntimeRegistryEntity,
        )

        row = session.scalar(
            select(StrategyRuntimeRegistryEntity).where(
                StrategyRuntimeRegistryEntity.strategy_definition_id
                == int(strategy_id),
            )
        )
        if row is not None and not bool(getattr(row, "enabled", False)):
            registry_ok = False
    except Exception:  # noqa: BLE001
        registry_ok = True
    if not registry_ok:
        return {
            "ok": False,
            "code": REASON_RUNTIME_REGISTRATION_NOT_READY,
            "approved": True,
        }
    return {
        "ok": True,
        "code": None,
        "approved": True,
        "is_active": True,
        "authorization_mode": auth.get("mode"),
        "backtest_run_id": auth.get("backtest_run_id"),
        "paper_run_id": auth.get("paper_run_id"),
    }


def evaluate_runtime_start_gates(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int,
    require_worker_running: bool = True,
) -> dict[str, Any]:
    """Runtime START 전 필수 gate. 하나라도 실패하면 START 금지."""

    return _evaluate_live_operating_gates(
        session,
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=int(strategy_id),
        require_worker_running=require_worker_running,
        require_strategy=True,
    )


def evaluate_runtime_run_gates(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int | None = None,
    enforce_pause: bool = True,
) -> dict[str, Any]:
    """실행 중 tick/주문 직전. 깨지면 신규 LIVE 주문 중지 + operator resume."""

    result = _evaluate_live_operating_gates(
        session,
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=strategy_id,
        require_worker_running=True,
        require_strategy=strategy_id is not None,
    )
    if not result["ok"] and enforce_pause:
        pause_upbit_runtimes_sync(
            int(user_broker_account_id),
            reason=str((result.get("blockers") or ["RUN_GATE_FAILED"])[0]),
        )
        result["runtime_paused"] = True
        result["resume_policy"] = RESUME_AFTER_SAFETY_BREAK
    else:
        result["runtime_paused"] = False
        result["resume_policy"] = RESUME_AFTER_SAFETY_BREAK
    return result


def _evaluate_live_operating_gates(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int | None,
    require_worker_running: bool,
    require_strategy: bool,
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "krx_hours_applied": False,
        "upbit_market_data_24x7": UPBIT_MARKET_DATA_24X7,
        "trading_scheduler_required": False,
    }
    blockers: list[str] = []
    uba_id = int(user_broker_account_id)

    uba = session.get(UserBrokerAccount, uba_id)
    if uba is None or not bool(uba.is_active) or getattr(uba, "deleted_at", None):
        blockers.append(REASON_UBA_INACTIVE)
        return {
            "ok": False,
            "blockers": blockers,
            "checks": checks,
        }
    broker = str(uba.broker_code or "").upper()
    checks["uba"] = {
        "user_broker_account_id": uba_id,
        "broker_code": broker,
        "is_active": True,
    }
    if broker != "UPBIT":
        blockers.append(REASON_UBA_BROKER_MISMATCH)

    try:
        assert_uba_connection_ready(uba, raise_error=_raise_error)
        checks["connection"] = {"ok": True, "status": uba.connection_status}
    except Upbit24x7ControlError:
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
    except Upbit24x7ControlError as exc:
        code = (
            REASON_TRADING_PAUSED
            if exc.code == "trading_paused"
            else REASON_RECOVERY_NOT_READY
        )
        blockers.append(code)
        checks["recovery"] = {"ok": False, "code": exc.code}

    try:
        risk = assert_risk_account_not_paused(
            session, uba, raise_error=_raise_error
        )
        checks["account_paused"] = {"ok": True, **risk}
    except Upbit24x7ControlError:
        blockers.append(REASON_ACCOUNT_PAUSED)
        checks["account_paused"] = {"ok": False}

    kill_on = False
    try:
        kill_on = _kill_active(session)
    except Exception:  # noqa: BLE001
        kill_on = True
    checks["kill_switch"] = {"ok": not kill_on, "active": kill_on}
    if kill_on:
        blockers.append(REASON_KILL_SWITCH_ACTIVE)

    try:
        act = _activation_active(session, uba_id)
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

    arm_ok, arm_detail = _arm_effective(uba)
    checks["arm"] = {"ok": arm_ok, **arm_detail}
    if not arm_ok:
        blockers.append(REASON_ARM_EXPIRED)

    if require_strategy and strategy_id is not None:
        strat = _strategy_ready(
            session, uba_id=uba_id, strategy_id=int(strategy_id)
        )
        checks["strategy"] = strat
        if not strat.get("ok"):
            blockers.append(str(strat.get("code") or REASON_STRATEGY_INACTIVE))

    worker_reason = live_outbox_queue_block_reason()
    worker_running = worker_reason is None
    from stock_platform.common.settings import get_settings
    from stock_platform.order.live_outbox_worker_runtime import (
        live_outbox_worker_runtime,
    )

    worker_status = live_outbox_worker_runtime.status()
    checks["outbox_worker"] = {
        "enabled": bool(worker_status.get("enabled")),
        "running": bool(worker_status.get("running")),
        "auto_start": bool(
            getattr(get_settings(), "live_outbox_worker_auto_start", False)
        ),
        "dispatch_allowed_if_running": False,
        "note": "RUNNING ≠ broker CREATE; dispatch fail-closed 별도",
    }
    if require_worker_running and not worker_running:
        # enabled=false 는 테스트 호환 — running 요구를 건너뛴다
        if bool(worker_status.get("enabled")):
            blockers.append(REASON_OUTBOX_WORKER_NOT_RUNNING)

    try:
        from stock_platform.realtime.live_runtime_control import (
            upbit_market_hours_policy,
        )

        checks["market_hours"] = upbit_market_hours_policy()
    except Exception:  # noqa: BLE001
        checks["market_hours"] = {
            "applies_krx_session": False,
            "policy": "24/7_SUBJECT_TO_RECOVERY_KILL_ARM",
        }

    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "ok": len(unique_blockers) == 0,
        "blockers": unique_blockers,
        "checks": checks,
        "resume_policy": RESUME_AFTER_SAFETY_BREAK,
    }


def pause_upbit_runtimes_sync(uba_id: int, *, reason: str) -> list[str]:
    """fail-closed pause. 재개는 operator START/RESUME만."""

    from stock_platform.realtime.runtime_bridge import (
        sync_realtime_consumer_for_entry,
    )
    from stock_platform.strategy_deployment.runtime_manager import (
        dynamic_strategy_runtime_manager,
    )

    paused: list[str] = []
    now = _now()
    for entry in dynamic_strategy_runtime_manager.list_entries(
        user_broker_account_id=int(uba_id)
    ):
        if str(entry.scope.broker_code or "").upper() != "UPBIT":
            continue
        if entry.status != RuntimeLifecycleStatus.RUNNING:
            continue
        entry.status = RuntimeLifecycleStatus.PAUSED
        entry.pause_reason = reason
        entry.last_paused_at = now
        entry.updated_at = now
        try:
            sync_realtime_consumer_for_entry(entry)
        except Exception:  # noqa: BLE001
            pass
        paused.append(entry.scope.scope_key)
    return paused


def _matching_runtime_entries(uba_id: int, strategy_id: int):
    from stock_platform.strategy_deployment.runtime_manager import (
        dynamic_strategy_runtime_manager,
    )

    return [
        entry
        for entry in dynamic_strategy_runtime_manager.list_entries(
            user_broker_account_id=int(uba_id),
            strategy_id=int(strategy_id),
        )
        if str(entry.scope.broker_code or "").upper() == "UPBIT"
    ]


def runtime_status_for_uba(
    *,
    user_broker_account_id: int,
    strategy_id: int | None = None,
    broker_code: str | None = None,
) -> dict[str, Any]:
    from stock_platform.strategy_deployment.runtime_manager import (
        dynamic_strategy_runtime_manager,
    )

    entries = dynamic_strategy_runtime_manager.list_entries(
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=None if strategy_id is None else int(strategy_id),
    )
    broker_u = str(broker_code or "").upper().strip()
    scoped = [
        e
        for e in entries
        if not broker_u
        or str(e.scope.broker_code or "").upper() == broker_u
    ]
    if not scoped:
        lifecycle = "STOPPED"
    elif any(e.status == RuntimeLifecycleStatus.ERROR for e in scoped):
        lifecycle = "ERROR"
    elif any(e.status == RuntimeLifecycleStatus.RUNNING for e in scoped):
        lifecycle = "RUNNING"
    elif any(e.status == RuntimeLifecycleStatus.PAUSED for e in scoped):
        lifecycle = "PAUSED"
    else:
        lifecycle = "STOPPED"
    last_heartbeat = None
    for entry in scoped:
        ts = getattr(entry, "last_heartbeat_at", None)
        if ts is None:
            continue
        if last_heartbeat is None or ts > last_heartbeat:
            last_heartbeat = ts
    return {
        "status": lifecycle,
        "entries": [e.as_dict() for e in scoped],
        "last_error": next(
            (e.last_error for e in scoped if e.last_error),
            None,
        ),
        "last_heartbeat_at": (
            last_heartbeat.isoformat() if last_heartbeat else None
        ),
        "independent_of_exit_monitor": True,
        "broker_code": broker_u or None,
    }


async def start_upbit_strategy_runtime(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int,
    actor: str,
    confirmation_text: str,
) -> dict[str, Any]:
    """명시적 Runtime START. KIWOOM Scope는 기동하지 않는다."""

    _ = actor
    _require_confirmation(confirmation_text, CONFIRM_START_RUNTIME)
    gates = evaluate_runtime_start_gates(
        session,
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=int(strategy_id),
        require_worker_running=True,
    )
    if not gates["ok"]:
        raise Upbit24x7ControlError(
            gates["blockers"][0],
            "Runtime START blocked: " + ",".join(gates["blockers"]),
        )

    uba = session.get(UserBrokerAccount, int(user_broker_account_id))
    if uba is None or str(uba.broker_code or "").upper() != "UPBIT":
        raise Upbit24x7ControlError(
            REASON_KIWOOM_ISOLATION,
            "UPBIT runtime start only",
        )

    existing = _matching_runtime_entries(
        int(user_broker_account_id), int(strategy_id)
    )
    running = [
        e for e in existing if e.status == RuntimeLifecycleStatus.RUNNING
    ]
    if running:
        for entry in running:
            entry.last_heartbeat_at = _now()
            entry.updated_at = _now()
        return {
            "started": True,
            "reason": "ALREADY_RUNNING",
            "idempotent": True,
            "gates": gates,
            "runtime": runtime_status_for_uba(
                user_broker_account_id=int(user_broker_account_id),
                strategy_id=int(strategy_id),
            ),
        }

    paused = [
        e for e in existing if e.status == RuntimeLifecycleStatus.PAUSED
    ]
    from stock_platform.strategy_deployment.runtime_manager import (
        dynamic_strategy_runtime_manager,
    )

    if paused:
        entry = paused[0]
        await dynamic_strategy_runtime_manager.resume_runtime(
            entry.scope.scope_key
        )
        entry.last_heartbeat_at = _now()
        return {
            "started": True,
            "reason": "RESUMED",
            "idempotent": False,
            "gates": gates,
            "runtime": runtime_status_for_uba(
                user_broker_account_id=int(user_broker_account_id),
                strategy_id=int(strategy_id),
            ),
        }

    from stock_platform.strategy_deployment.runtime_bootstrap import (
        _build_scope_for_link,
    )

    link = session.scalar(
        select(AccountStrategyLinkEntity).where(
            AccountStrategyLinkEntity.user_broker_account_id
            == int(user_broker_account_id),
            AccountStrategyLinkEntity.strategy_id == int(strategy_id),
            AccountStrategyLinkEntity.is_active.is_(True),
        )
    )
    if link is None:
        raise Upbit24x7ControlError(
            REASON_RUNTIME_REGISTRATION_NOT_READY,
            "active account_strategy_link required",
        )
    scope, _start = _build_scope_for_link(session, link, kill_active=False)
    if str(scope.broker_code or "").upper() != "UPBIT":
        raise Upbit24x7ControlError(
            REASON_KIWOOM_ISOLATION,
            "refusing non-UPBIT scope start",
        )
    await dynamic_strategy_runtime_manager.initialize_scoped(
        scope, force=True, start=True
    )
    started = _matching_runtime_entries(
        int(user_broker_account_id), int(strategy_id)
    )
    for entry in started:
        entry.last_heartbeat_at = _now()
    return {
        "started": True,
        "reason": "STARTED",
        "idempotent": False,
        "gates": gates,
        "runtime": runtime_status_for_uba(
            user_broker_account_id=int(user_broker_account_id),
            strategy_id=int(strategy_id),
        ),
    }


async def stop_upbit_strategy_runtime(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int,
    confirmation_text: str,
) -> dict[str, Any]:
    """Runtime STOP. Exit Monitor는 건드리지 않는다."""

    _ = session
    _require_confirmation(confirmation_text, CONFIRM_STOP_RUNTIME)
    from stock_platform.strategy_deployment.runtime_manager import (
        dynamic_strategy_runtime_manager,
    )

    entries = _matching_runtime_entries(
        int(user_broker_account_id), int(strategy_id)
    )
    if not entries or all(
        e.status == RuntimeLifecycleStatus.STOPPED for e in entries
    ):
        return {
            "stopped": True,
            "reason": "ALREADY_STOPPED",
            "idempotent": True,
            "exit_monitor_untouched": True,
            "runtime": runtime_status_for_uba(
                user_broker_account_id=int(user_broker_account_id),
                strategy_id=int(strategy_id),
            ),
        }
    for entry in entries:
        if entry.status == RuntimeLifecycleStatus.STOPPED:
            continue
        await dynamic_strategy_runtime_manager.stop_runtime(
            entry.scope.scope_key
        )
    return {
        "stopped": True,
        "reason": "STOPPED",
        "idempotent": False,
        "exit_monitor_untouched": True,
        "runtime": runtime_status_for_uba(
            user_broker_account_id=int(user_broker_account_id),
            strategy_id=int(strategy_id),
        ),
    }


def start_live_outbox_worker(*, confirmation_text: str) -> dict[str, Any]:
    """Worker 프로세스 START. LIVE/ARM/Activation을 켜지 않는다."""

    _require_confirmation(confirmation_text, CONFIRM_START_WORKER)
    from stock_platform.order.live_outbox_worker_runtime import (
        live_outbox_worker_runtime,
    )

    result = live_outbox_worker_runtime.start()
    started = bool(result.get("started")) or result.get("reason") == (
        "ALREADY_RUNNING"
    )
    if result.get("reason") == "LIVE_OUTBOX_WORKER_DISABLED":
        raise Upbit24x7ControlError(
            REASON_WORKER_DISABLED,
            "live_outbox_worker_enabled=false",
        )
    return {
        **result,
        "started": started,
        "idempotent": result.get("reason") == "ALREADY_RUNNING",
        "auto_start_policy": WORKER_AUTO_START_POLICY,
        "dispatch_not_implied": True,
        "kiwoom_runtime_started": False,
    }


def stop_live_outbox_worker(*, confirmation_text: str) -> dict[str, Any]:
    _require_confirmation(confirmation_text, CONFIRM_STOP_WORKER)
    from stock_platform.order.live_outbox_worker_runtime import (
        live_outbox_worker_runtime,
    )

    result = live_outbox_worker_runtime.stop()
    return {
        **result,
        "idempotent": result.get("reason") == "ALREADY_STOPPED",
        "auto_start_policy": WORKER_AUTO_START_POLICY,
    }


def exit_monitor_status() -> dict[str, Any]:
    from stock_platform.position.exit_monitor_runtime import (
        position_exit_monitor_manager,
    )
    from stock_platform.position.exit_monitor_scheduler import (
        position_exit_monitor_scheduler,
    )

    manager = position_exit_monitor_manager.status()
    scheduler_running = bool(
        getattr(
            getattr(position_exit_monitor_scheduler, "scheduler", None),
            "running",
            False,
        )
    )
    live_upbit = bool(manager.get("live_upbit_enabled"))
    enabled = bool(manager.get("enabled"))
    if manager.get("last_error"):
        lifecycle = "ERROR"
    elif scheduler_running and enabled:
        lifecycle = "RUNNING"
    else:
        lifecycle = "STOPPED"
    return {
        "status": lifecycle,
        "scheduler_running": scheduler_running,
        "independent_of_strategy_runtime": True,
        "live_upbit_scan_enabled": live_upbit,
        "orders_via_oes_only": True,
        "start_without_activation_allowed": True,
        "broker_submit_requires_oes_fail_closed": True,
        **manager,
    }


def start_exit_monitor(*, confirmation_text: str) -> dict[str, Any]:
    """Monitor 프로세스 START. live_upbit 플래그는 변경하지 않는다."""

    _require_confirmation(confirmation_text, CONFIRM_START_EXIT_MONITOR)
    from stock_platform.position.exit_monitor_scheduler import (
        position_exit_monitor_scheduler,
    )

    position_exit_monitor_scheduler.start()
    return {
        "started": True,
        "live_upbit_flag_unchanged": True,
        "status": exit_monitor_status(),
    }


async def stop_exit_monitor(*, confirmation_text: str) -> dict[str, Any]:
    _require_confirmation(confirmation_text, CONFIRM_STOP_EXIT_MONITOR)
    from stock_platform.position.exit_monitor_scheduler import (
        position_exit_monitor_scheduler,
    )

    await position_exit_monitor_scheduler.shutdown()
    return {
        "stopped": True,
        "status": exit_monitor_status(),
    }


def combined_control_status(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int | None = None,
) -> dict[str, Any]:
    """운영 UI/health용 최소 status. 상태 변경 없음."""

    uba = session.get(UserBrokerAccount, int(user_broker_account_id))
    live_on = bool(getattr(uba, "live_order_enabled", False)) if uba else False
    arm_ok, arm_detail = (
        _arm_effective(uba) if uba is not None else (False, {})
    )
    activation_label = "INACTIVE"
    try:
        act = _activation_active(session, int(user_broker_account_id))
        if act.get("ok"):
            activation_label = "ACTIVE"
    except Exception:  # noqa: BLE001
        activation_label = "INACTIVE"

    from stock_platform.order.live_outbox_worker_runtime import (
        live_outbox_worker_runtime,
    )

    worker = live_outbox_worker_runtime.status()
    if worker.get("last_error") and bool(worker.get("running")):
        worker_lifecycle = "ERROR"
    elif bool(worker.get("running")):
        worker_lifecycle = "RUNNING"
    else:
        worker_lifecycle = "STOPPED"

    runtime = runtime_status_for_uba(
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=strategy_id,
        broker_code=(
            str(uba.broker_code).upper() if uba is not None else None
        ),
    )
    exit_st = exit_monitor_status()
    return {
        "user_broker_account_id": int(user_broker_account_id),
        "broker_code": (
            str(uba.broker_code).upper() if uba is not None else None
        ),
        "activation": activation_label,
        "live": "ON" if live_on else "OFF",
        "arm": "ACTIVE" if arm_ok else "EXPIRED",
        "arm_detail": arm_detail,
        "strategy_runtime": runtime["status"],
        "outbox_worker": worker_lifecycle,
        "exit_monitor": exit_st["status"],
        "runtime": runtime,
        "worker": worker,
        "exit_monitor_detail": exit_st,
        "operating_start_sequence": list(OPERATING_START_SEQUENCE),
        "operating_stop_sequence": list(OPERATING_STOP_SEQUENCE),
        "restart_policy": dict(RESTART_POLICY),
        "worker_auto_start_policy": WORKER_AUTO_START_POLICY,
        "resume_after_safety_break": RESUME_AFTER_SAFETY_BREAK,
        "upbit_market_data_24x7": UPBIT_MARKET_DATA_24X7,
        "start_all_forbidden": True,
        "trading_scheduler_required": False,
        "scanner_policy": "SHADOW_ONLY",
    }


def build_24x7_ops_health() -> dict[str, Any]:
    """ /health/ops additive — DB 변경 없음. """

    from stock_platform.order.live_outbox_worker_runtime import (
        live_outbox_worker_runtime,
    )
    from stock_platform.strategy_deployment.runtime_manager import (
        dynamic_strategy_runtime_manager,
    )

    worker = live_outbox_worker_runtime.status()
    mgr = dynamic_strategy_runtime_manager.status()
    exit_st = exit_monitor_status()
    worker_life = (
        "ERROR"
        if worker.get("last_error") and worker.get("running")
        else ("RUNNING" if worker.get("running") else "STOPPED")
    )
    return {
        "status": "UP",
        "strategy_runtime": {
            "status": (
                "RUNNING"
                if int(mgr.get("scoped_runtime_count") or 0) > 0
                and any(
                    str(row.get("status")) == "RUNNING"
                    for row in (mgr.get("runtimes") or [])
                )
                else "STOPPED"
            ),
            "scoped_runtime_count": mgr.get("scoped_runtime_count"),
            "last_error": mgr.get("last_error"),
        },
        "live_outbox_worker": {
            "status": worker_life,
            **{
                k: worker.get(k)
                for k in (
                    "enabled",
                    "auto_start",
                    "running",
                    "last_run_at",
                    "last_error",
                )
            },
        },
        "live_exit_monitor": {
            "status": exit_st.get("status"),
            "scheduler_running": exit_st.get("scheduler_running"),
            "live_upbit_enabled": exit_st.get("live_upbit_scan_enabled"),
            "last_error": exit_st.get("last_error"),
        },
        "upbit_market_data_24x7": UPBIT_MARKET_DATA_24X7,
        "worker_running_not_dispatch_allowed": True,
    }
