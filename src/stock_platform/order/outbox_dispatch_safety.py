"""LIVE Outbox dispatch 직전 fail-closed 안전 게이트.

QUEUED 이후 Kill/Pause/Recovery/Credential/Connection/Activation/ARM
이 바뀌어도 broker CREATE 직전에 재검사한다.

PAPER/MOCK 경로는 검사하지 않는다 (기존 동작 유지).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.order.live_safety_audit import (
    LIVE_REJECTED,
    emit_live_safety_audit,
)
from stock_platform.order.outbox_fencing import record_outbox_audit
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.runtime_control_gates import (
    assert_recovery_ready,
    assert_risk_account_not_paused,
    assert_uba_connection_ready,
)


# 기존 프로젝트 코드를 재사용한다. 동일 의미 신규 코드는 만들지 않는다.
REASON_ACTIVATION_INACTIVE = "ACTIVATION_INACTIVE"
REASON_LIVE_DISABLED = "LIVE_ORDER_DISABLED"  # 예: LIVE_DISABLED
REASON_ARM_INACTIVE = "LIVE_NOT_ARMED"  # 예: ARM_INACTIVE
REASON_ARM_EXPIRED = "LIVE_ARM_EXPIRED"
REASON_KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
REASON_KILL_SWITCH_UNAVAILABLE = "KILL_SWITCH_UNAVAILABLE"
REASON_TRADING_PAUSED = "TRADING_PAUSED"
REASON_RECOVERY_NOT_READY = "RECOVERY_NOT_READY"
REASON_CREDENTIAL_NOT_READY = "CREDENTIAL_NOT_READY"
REASON_CONNECTION_NOT_READY = "CONNECTION_NOT_CONNECTED"  # 기존 SCREAMING
REASON_ACCOUNT_PAUSED = "ACCOUNT_PAUSED"
REASON_ACCOUNT_INACTIVE = "ACCOUNT_INACTIVE"
REASON_UBA_REQUIRED = "UBA_REQUIRED"
REASON_UBA_BROKER_MISMATCH = "UBA_BROKER_MISMATCH"
REASON_UBA_OWNERSHIP_MISMATCH = "UBA_OWNERSHIP_MISMATCH"

AUDIT_EVENT_DISPATCH_SAFETY_REJECTED = "OUTBOX_DISPATCH_SAFETY_REJECTED"

# runtime_control_gates 스네이크 코드 → dispatch 식별자
_GATE_CODE_MAP = {
    "trading_paused": REASON_TRADING_PAUSED,
    "recovery_not_ready": REASON_RECOVERY_NOT_READY,
    "account_paused": REASON_ACCOUNT_PAUSED,
    "connection_not_connected": REASON_CONNECTION_NOT_READY,
}

_SECRET_DETAIL_KEYS = frozenset(
    {
        "token",
        "arm_token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "secret_key",
        "api_key",
        "api_secret",
        "access_key",
        "authorization",
        "account_number",
        "payload_json",
    }
)


class OutboxDispatchSafetyError(PermissionError):
    """LIVE dispatch 안전 게이트 실패 — broker 호출 금지, 자동 RETRY 금지."""

    def __init__(
        self,
        reason_code: str,
        message: str | None = None,
        *,
        detail_code: str | None = None,
    ) -> None:
        self.reason_code = str(reason_code)
        self.detail_code = detail_code
        super().__init__(message or reason_code)


def assert_live_outbox_dispatch_safety(
    session: Session,
    payload: dict[str, Any],
    *,
    outbox_id: int | None = None,
    outbox_idempotency_key: str | None = None,
) -> None:
    """LIVE SUBMIT 직전 계좌 안전상태를 재검증한다. PAPER는 no-op."""

    env = str(payload.get("environment") or "PAPER").upper()
    if env != "LIVE":
        return

    from stock_platform.broker.live_config_gate import (
        evaluate_live_flag_consistency,
    )
    from stock_platform.broker.live_transition_guard import (
        LiveTradingTransitionGuard,
    )
    from stock_platform.operation.live_health_gate import (
        assert_live_orders_allowed,
    )

    payload_broker = str(payload.get("broker_code") or "").upper()
    uba_raw = payload.get("user_broker_account_id")
    uba_id_probe = None if uba_raw in (None, "") else int(uba_raw)
    cfg = evaluate_live_flag_consistency(
        broker_code=payload_broker or None,
        session=session,
        user_broker_account_id=uba_id_probe,
        uses_system_shared_credential=bool(
            payload.get("uses_system_shared_credential")
        ),
        credential_ref=(
            None
            if payload.get("credential_ref") in (None, "")
            else str(payload.get("credential_ref"))
        ),
    )
    if cfg.code in {
        "LIVE_FLAG_MISMATCH_KIWOOM",
        "GLOBAL_LIVE_OFF",
        "UPBIT_LIVE_OFF",
        "UPBIT_MOCK_LIVE_CONFLICT",
    }:
        raise OutboxDispatchSafetyError(cfg.code, cfg.code)
    # KIWOOM 전용. UPBIT는 위 broker-scoped 평가에서 이미 통과/차단됨.
    if cfg.code == "LIVE_MOCK_CONFLICT" and payload_broker != "UPBIT":
        from stock_platform.broker.kiwoom.execution_env import (
            kiwoom_global_mock_blocks_live_execution,
        )

        uba_raw = payload.get("user_broker_account_id")
        uba_id_probe = None if uba_raw in (None, "") else int(uba_raw)
        if kiwoom_global_mock_blocks_live_execution(
            session,
            user_broker_account_id=uba_id_probe,
            uses_system_shared_credential=bool(
                payload.get("uses_system_shared_credential")
            ),
            credential_ref=(
                None
                if payload.get("credential_ref") in (None, "")
                else str(payload.get("credential_ref"))
            ),
        ):
            raise OutboxDispatchSafetyError(cfg.code, cfg.code)
    assert_live_orders_allowed(session)

    uba_raw = payload.get("user_broker_account_id")
    if uba_raw is None:
        raise OutboxDispatchSafetyError(
            REASON_UBA_REQUIRED, REASON_UBA_REQUIRED
        )
    uba_id = int(uba_raw)
    uba = session.get(UserBrokerAccount, uba_id)
    if uba is None or not bool(uba.is_active):
        raise OutboxDispatchSafetyError(
            REASON_ACCOUNT_INACTIVE, REASON_ACCOUNT_INACTIVE
        )
    expected_broker = str(payload.get("broker_code") or "").upper()
    uba_broker = str(uba.broker_code).upper()
    if expected_broker and uba_broker != expected_broker:
        raise OutboxDispatchSafetyError(
            REASON_UBA_BROKER_MISMATCH, REASON_UBA_BROKER_MISMATCH
        )
    dispatch_broker = expected_broker or uba_broker

    # 1) Activation effective ACTIVE
    try:
        LiveTradingTransitionGuard(session).require_active(
            broker_code=dispatch_broker,
            user_broker_account_id=uba_id,
        )
    except OutboxDispatchSafetyError:
        raise
    except PermissionError as exc:
        raise OutboxDispatchSafetyError(
            REASON_ACTIVATION_INACTIVE,
            str(exc) or REASON_ACTIVATION_INACTIVE,
        ) from exc

    owner_raw = payload.get("owner_user_id")
    if owner_raw not in (None, "") and int(uba.user_id) != int(owner_raw):
        raise OutboxDispatchSafetyError(
            REASON_UBA_OWNERSHIP_MISMATCH,
            REASON_UBA_OWNERSHIP_MISMATCH,
        )

    from stock_platform.trading.live_arm_service import LiveArmService

    # ARM 만료 시 LIVE OFF — lazy expiry 유지
    expired = LiveArmService(session).expire_if_needed(uba_id)
    uba = session.get(UserBrokerAccount, uba_id)
    if uba is None:
        raise OutboxDispatchSafetyError(
            REASON_ACCOUNT_INACTIVE, REASON_ACCOUNT_INACTIVE
        )
    live_on = bool(getattr(uba, "live_order_enabled", False))
    armed = bool(getattr(uba, "live_armed", False))

    # 2) LIVE ON  3) ARM ON + TTL — smoke one-shot 만 예외
    if not (live_on and armed and not expired):
        _assert_live_arm_or_smoke_grant(
            session,
            payload,
            uba_id=uba_id,
            outbox_id=outbox_id,
            outbox_idempotency_key=outbox_idempotency_key,
            live_on=live_on,
            armed=armed,
            expired=bool(expired),
            dispatch_broker=dispatch_broker,
        )

    # 4)~9) Kill / trading_paused / Recovery / Credential / Connection / pause
    assert_live_outbox_account_runtime_gates(
        session,
        uba,
        uba_id=uba_id,
        broker_code=dispatch_broker,
    )


def assert_live_outbox_account_runtime_gates(
    session: Session,
    uba: UserBrokerAccount,
    *,
    uba_id: int,
    broker_code: str,
) -> None:
    """Kill / Pause / Recovery / Credential / Connection / account_paused."""

    _assert_kill_switch_off(session, uba=uba, uba_id=uba_id)
    _assert_recovery_and_trading_not_paused(session, uba_id)
    _assert_credential_ready(session, uba_id=uba_id, broker_code=broker_code)
    _assert_connection_ready(uba)
    _assert_account_not_paused(session, uba)


def emit_outbox_dispatch_safety_rejection(
    session: Session,
    *,
    reason_code: str,
    payload: dict[str, Any],
    outbox_id: int | None,
    worker_id: str,
    trading_order_id: int | None = None,
) -> None:
    """거절 audit — secret/키/ARM 원문 금지."""

    uba_raw = payload.get("user_broker_account_id")
    uba_id = None if uba_raw in (None, "") else int(uba_raw)
    order_id = trading_order_id
    if order_id is None:
        order_raw = payload.get("order_id")
        order_id = None if order_raw in (None, "") else int(order_raw)
    broker = str(payload.get("broker_code") or "").upper() or None
    now = datetime.now(timezone.utc)
    detail = _safe_audit_detail(
        {
            "outbox_id": outbox_id,
            "trading_order_id": order_id,
            "order_id": order_id,
            "user_broker_account_id": uba_id,
            "broker": broker,
            "broker_code": broker,
            "reason_code": reason_code,
            "timestamp": now.isoformat(),
            "environment": str(payload.get("environment") or "").upper(),
        }
    )
    try:
        emit_live_safety_audit(
            session,
            event_type=LIVE_REJECTED,
            actor=worker_id,
            run_id=None,
            user_id=(
                None
                if payload.get("owner_user_id") in (None, "")
                else int(payload.get("owner_user_id"))
            ),
            account_id=uba_id,
            strategy_id=None,
            order_id=order_id,
            detail=detail,
            commit=False,
        )
    except Exception:  # noqa: BLE001
        pass
    record_outbox_audit(
        session,
        event_type=AUDIT_EVENT_DISPATCH_SAFETY_REJECTED,
        detail=detail,
        actor=worker_id,
    )


def _assert_live_arm_or_smoke_grant(
    session: Session,
    payload: dict[str, Any],
    *,
    uba_id: int,
    outbox_id: int | None,
    outbox_idempotency_key: str | None,
    live_on: bool,
    armed: bool,
    expired: bool,
    dispatch_broker: str,
) -> None:
    if outbox_id is None:
        if not live_on:
            raise OutboxDispatchSafetyError(
                REASON_LIVE_DISABLED, REASON_LIVE_DISABLED
            )
        if expired or not armed:
            code = REASON_ARM_EXPIRED if expired else REASON_ARM_INACTIVE
            raise OutboxDispatchSafetyError(code, code)
        return

    from stock_platform.order.live_safety_audit import emit_live_safety_audit
    from stock_platform.trading.smoke_one_shot_dispatch_grant import (
        SmokeOneShotGrantError,
        assert_smoke_one_shot_dispatch_allowed,
    )
    from stock_platform.trading.upbit_live_smoke_constants import (
        UPBIT_LIVE_SMOKE_ONE_SHOT_DISPATCH_ALLOWED,
    )

    try:
        grant = assert_smoke_one_shot_dispatch_allowed(
            session,
            payload,
            outbox_id=int(outbox_id),
            outbox_idempotency_key=outbox_idempotency_key,
        )
    except SmokeOneShotGrantError as exc:
        if not live_on:
            raise OutboxDispatchSafetyError(
                REASON_LIVE_DISABLED,
                f"{REASON_LIVE_DISABLED}:{exc}",
            ) from exc
        code = REASON_ARM_EXPIRED if expired else REASON_ARM_INACTIVE
        raise OutboxDispatchSafetyError(code, f"{code}:{exc}") from exc

    try:
        emit_live_safety_audit(
            session,
            event_type=UPBIT_LIVE_SMOKE_ONE_SHOT_DISPATCH_ALLOWED,
            actor="OUTBOX_WORKER",
            run_id=str(grant.get("run_id") or ""),
            user_id=int(grant.get("owner_user_id") or 0) or None,
            account_id=int(uba_id),
            strategy_id=None,
            order_id=int(payload.get("order_id") or 0) or None,
            detail={
                "outbox_id": int(outbox_id),
                "order_id": grant.get("order_id"),
                "run_id": grant.get("run_id"),
                "arm_deadline_at": grant.get("arm_deadline_at"),
                "dispatch_expires_at": grant.get("dispatch_expires_at"),
                "live_on": live_on,
                "armed": armed,
                "activation_broker": dispatch_broker,
                "activation_uba": int(uba_id),
            },
            commit=False,
        )
    except Exception:  # noqa: BLE001
        pass


def _assert_kill_switch_off(
    session: Session,
    *,
    uba: UserBrokerAccount,
    uba_id: int,
) -> None:
    from stock_platform.risk_engine.kill_switch_service import KillSwitchService
    from stock_platform.trading.account_identity import uba_kill_switch_scope

    try:
        ks = KillSwitchService(session)
        scopes = [
            KillSwitchService.GLOBAL_SCOPE,
            uba_kill_switch_scope(int(uba_id)),
            f"USER:{int(uba.user_id)}",
        ]
        if ks.is_active_for_scopes(scopes):
            raise OutboxDispatchSafetyError(
                REASON_KILL_SWITCH_ACTIVE,
                REASON_KILL_SWITCH_ACTIVE,
            )
    except OutboxDispatchSafetyError:
        raise
    except Exception as exc:  # noqa: BLE001 — 조회 실패는 fail-closed
        raise OutboxDispatchSafetyError(
            REASON_KILL_SWITCH_UNAVAILABLE,
            REASON_KILL_SWITCH_UNAVAILABLE,
        ) from exc


def _assert_recovery_and_trading_not_paused(
    session: Session, uba_id: int
) -> None:
    def _raise(code: str, message: str) -> OutboxDispatchSafetyError:
        mapped = _GATE_CODE_MAP.get(code, code.upper())
        if mapped == "RECOVERY_NOT_READY" or code == "recovery_not_ready":
            mapped = REASON_RECOVERY_NOT_READY
        return OutboxDispatchSafetyError(mapped, message)

    assert_recovery_ready(session, uba_id, raise_error=_raise)


def _assert_credential_ready(
    session: Session,
    *,
    uba_id: int,
    broker_code: str,
) -> None:
    """active + VERIFIED 만 허용. payload/키 원문은 읽지 않는다."""

    from stock_platform.broker.credential_vault_service import (
        BrokerCredentialVaultService,
    )

    try:
        entity = BrokerCredentialVaultService(session).get_active_entity(
            int(uba_id)
        )
    except Exception as exc:  # noqa: BLE001
        raise OutboxDispatchSafetyError(
            REASON_CREDENTIAL_NOT_READY,
            REASON_CREDENTIAL_NOT_READY,
            detail_code="credential_lookup_failed",
        ) from exc
    if entity is None or not bool(getattr(entity, "is_active", False)):
        raise OutboxDispatchSafetyError(
            REASON_CREDENTIAL_NOT_READY,
            REASON_CREDENTIAL_NOT_READY,
            detail_code="credential_inactive",
        )
    expected = str(broker_code or "").upper()
    actual = str(getattr(entity, "broker_code", "") or "").upper()
    if expected and actual and actual != expected:
        raise OutboxDispatchSafetyError(
            REASON_CREDENTIAL_NOT_READY,
            REASON_CREDENTIAL_NOT_READY,
            detail_code="credential_broker_mismatch",
        )
    status = str(getattr(entity, "verification_status", "") or "").upper()
    if status != "VERIFIED":
        raise OutboxDispatchSafetyError(
            REASON_CREDENTIAL_NOT_READY,
            REASON_CREDENTIAL_NOT_READY,
            detail_code="credential_unverified",
        )
    if getattr(entity, "revoked_at", None) is not None:
        raise OutboxDispatchSafetyError(
            REASON_CREDENTIAL_NOT_READY,
            REASON_CREDENTIAL_NOT_READY,
            detail_code="credential_revoked",
        )
    expires = getattr(entity, "expires_at", None)
    if expires is not None:
        exp = expires
        if getattr(exp, "tzinfo", None) is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            raise OutboxDispatchSafetyError(
                REASON_CREDENTIAL_NOT_READY,
                REASON_CREDENTIAL_NOT_READY,
                detail_code="credential_expired",
            )


def _assert_connection_ready(uba: UserBrokerAccount) -> None:
    def _raise(code: str, message: str) -> OutboxDispatchSafetyError:
        mapped = _GATE_CODE_MAP.get(code, REASON_CONNECTION_NOT_READY)
        return OutboxDispatchSafetyError(mapped, message)

    assert_uba_connection_ready(uba, raise_error=_raise)


def _assert_account_not_paused(
    session: Session, uba: UserBrokerAccount
) -> None:
    def _raise(code: str, message: str) -> OutboxDispatchSafetyError:
        mapped = _GATE_CODE_MAP.get(code, code.upper())
        return OutboxDispatchSafetyError(mapped, message)

    assert_risk_account_not_paused(session, uba, raise_error=_raise)


def _safe_audit_detail(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in detail.items()
        if str(k).lower() not in _SECRET_DETAIL_KEYS
    }
