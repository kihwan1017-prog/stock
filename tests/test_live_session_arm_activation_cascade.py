"""UPBIT session ARM TTL clamp + Activation expiry cascade.

fixture/mock only. 실 Activation/LIVE/ARM/주문 금지.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.outbox_worker import OrderOutboxWorker
from stock_platform.trading.live_arm_service import (
    DEFAULT_ARM_TTL_SECONDS,
    LiveArmError,
    LiveArmService,
)
from stock_platform.trading.live_session_expiry import (
    expire_enabled_activation,
    revoke_stale_live_without_activation,
    scan_and_expire_live_sessions,
)
from stock_platform.trading.live_session_expiry_runtime import (
    LiveSessionExpiryRuntime,
)

# _expire_uba 가 함수 내부 import 하므로 원본 모듈을 패치한다.
_SCHEDULER_CTRL = (
    "stock_platform.trading.trading_scheduler_control_service"
    ".TradingSchedulerControlService"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uba(
    *,
    uba_id: int,
    broker: str,
    live: bool = True,
    armed: bool = True,
    token_hash: str = "hash",
    arm_hours: int = 8,
):
    now = _now()
    return SimpleNamespace(
        user_broker_account_id=uba_id,
        user_id=61 if uba_id == 1380 else 61,
        broker_code=broker,
        is_active=True,
        live_order_enabled=live,
        live_armed=armed,
        arm_token_hash=token_hash,
        arm_expires_at=now + timedelta(hours=arm_hours),
        arm_armed_by="admin",
        arm_armed_at=now,
        live_approved_at=now,
        live_approved_by="admin",
    )


def _activation(
    *,
    uba_id: int,
    broker: str,
    remaining_seconds: int,
    enabled: bool = True,
    tid: int = 1,
):
    now = _now()
    return SimpleNamespace(
        live_trading_transition_id=tid,
        enabled=enabled,
        activation_status="ACTIVE" if enabled else "EXPIRED",
        expires_at=now + timedelta(seconds=remaining_seconds),
        broker_code=broker,
        scope="ACCOUNT",
        user_broker_account_id=uba_id,
        disable_reason=None,
        disabled_at=None,
    )


def _policy_ttl(seconds: int = 300):
    return SimpleNamespace(arm_ttl_seconds=seconds)


@pytest.fixture
def pause_ok():
    with patch(
        "stock_platform.trading.live_session_expiry._try_scheduler_pause",
        return_value=True,
    ) as p:
        yield p


def test_arm_clamp_request_equals_remaining() -> None:
    session = MagicMock()
    uba = _uba(uba_id=1380, broker="UPBIT", armed=False)
    session.get.return_value = uba
    act = _activation(uba_id=1380, broker="UPBIT", remaining_seconds=8 * 3600)
    svc = LiveArmService(session)
    with patch.object(svc, "_require_session_activation", return_value=act):
        effective, expires, entity = svc._clamp_arm_ttl(
            uba, 8 * 3600, 300
        )
    assert entity is act
    assert effective <= 8 * 3600
    assert expires <= act.expires_at


def test_arm_clamp_request_exceeds_remaining() -> None:
    session = MagicMock()
    uba = _uba(uba_id=1380, broker="UPBIT", armed=False)
    act = _activation(uba_id=1380, broker="UPBIT", remaining_seconds=30 * 60)
    svc = LiveArmService(session)
    with patch.object(svc, "_require_session_activation", return_value=act):
        effective, expires, _ = svc._clamp_arm_ttl(
            uba, 8 * 3600, 300
        )
    assert effective == 30 * 60
    assert expires <= act.expires_at
    assert expires > _now() - timedelta(seconds=2)


def test_arm_rejects_when_activation_remaining_zero() -> None:
    session = MagicMock()
    uba = _uba(uba_id=1380, broker="UPBIT", armed=False)
    act = _activation(uba_id=1380, broker="UPBIT", remaining_seconds=0)
    act.expires_at = _now() - timedelta(seconds=1)
    svc = LiveArmService(session)
    with patch.object(svc, "_require_session_activation", return_value=act):
        with pytest.raises(LiveArmError) as ei:
            svc._clamp_arm_ttl(uba, 300, 300)
    assert ei.value.code == "ACTIVATION_INACTIVE"


def test_arm_rejects_when_no_activation() -> None:
    session = MagicMock()
    uba = _uba(uba_id=1380, broker="UPBIT", armed=False)
    session.get.return_value = uba
    svc = LiveArmService(session)
    with patch(
        "stock_platform.broker.live_transition_service.LiveTradingTransitionService.peek_active",
        return_value=None,
    ):
        with pytest.raises(LiveArmError) as ei:
            svc._require_session_activation(uba)
    assert ei.value.code == "ACTIVATION_INACTIVE"


def test_activation_expiry_cascade_live_arm_scheduler(pause_ok) -> None:
    session = MagicMock()
    uba = _uba(uba_id=1380, broker="UPBIT")
    session.get.return_value = uba
    act = _activation(uba_id=1380, broker="UPBIT", remaining_seconds=-1)
    act.expires_at = _now() - timedelta(minutes=1)
    with (
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
        patch(_SCHEDULER_CTRL),
    ):
        out = expire_enabled_activation(session, act, actor="TEST")
    assert act.enabled is False
    assert act.activation_status == "EXPIRED"
    assert uba.live_order_enabled is False
    assert uba.live_armed is False
    assert uba.arm_token_hash is None
    assert uba.arm_expires_at is None
    assert out["live_off"] is True
    assert out["arm_off"] is True
    assert pause_ok.called
    detail = audit.call_args.kwargs["detail"]
    assert detail["activation_id"] == act.live_trading_transition_id
    assert detail["user_broker_account_id"] == 1380
    assert detail["broker_code"] == "UPBIT"
    assert "arm_token" not in detail
    assert "access_key" not in str(detail)
    assert "secret" not in str(detail).lower()


def test_activation_expiry_pause_failure_still_live_arm_off() -> None:
    session = MagicMock()
    uba = _uba(uba_id=1380, broker="UPBIT")
    session.get.return_value = uba
    act = _activation(uba_id=1380, broker="UPBIT", remaining_seconds=-1)
    act.expires_at = _now() - timedelta(minutes=1)
    with (
        patch(
            "stock_platform.trading.live_session_expiry._try_scheduler_pause",
            return_value=False,
        ),
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
        patch(_SCHEDULER_CTRL) as sched_cls,
    ):
        sched_cls.return_value.pause.side_effect = RuntimeError("pause failed")
        out = expire_enabled_activation(session, act, actor="TEST")
    assert uba.live_order_enabled is False
    assert uba.live_armed is False
    assert out["scheduler_paused"] is False
    assert out["live_off"] is True
    assert out["arm_off"] is True


def test_activation_expiry_idempotent(pause_ok) -> None:
    session = MagicMock()
    uba = _uba(uba_id=1380, broker="UPBIT", live=False, armed=False)
    uba.arm_token_hash = None
    uba.arm_expires_at = None
    session.get.return_value = uba
    act = _activation(
        uba_id=1380, broker="UPBIT", remaining_seconds=-1, enabled=False
    )
    act.expires_at = _now() - timedelta(minutes=1)
    with (
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_order_telegram"
        ),
    ):
        first = expire_enabled_activation(session, act, actor="TEST")
        second = expire_enabled_activation(session, act, actor="TEST")
    assert first["idempotent"] is True
    assert second["idempotent"] is True
    assert uba.live_order_enabled is False
    assert uba.live_armed is False


def test_cross_uba_isolation_1380_expiry_leaves_1381(pause_ok) -> None:
    session = MagicMock()
    uba1380 = _uba(uba_id=1380, broker="UPBIT")
    uba1381 = _uba(uba_id=1381, broker="KIWOOM")
    session.get.side_effect = lambda _cls, pk: (
        uba1380 if int(pk) == 1380 else uba1381 if int(pk) == 1381 else None
    )
    act = _activation(uba_id=1380, broker="UPBIT", remaining_seconds=-1, tid=10)
    act.expires_at = _now() - timedelta(minutes=1)
    with (
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
        patch(_SCHEDULER_CTRL),
    ):
        expire_enabled_activation(session, act, actor="TEST")
    assert uba1380.live_order_enabled is False
    assert uba1380.live_armed is False
    assert uba1381.live_order_enabled is True
    assert uba1381.live_armed is True
    assert uba1381.arm_token_hash == "hash"


def test_cross_uba_isolation_1381_expiry_leaves_1380(pause_ok) -> None:
    session = MagicMock()
    uba1380 = _uba(uba_id=1380, broker="UPBIT")
    uba1381 = _uba(uba_id=1381, broker="KIWOOM")
    session.get.side_effect = lambda _cls, pk: (
        uba1380 if int(pk) == 1380 else uba1381 if int(pk) == 1381 else None
    )
    act = _activation(uba_id=1381, broker="KIWOOM", remaining_seconds=-1, tid=11)
    act.expires_at = _now() - timedelta(minutes=1)
    with (
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
        patch(
            _SCHEDULER_CTRL
        ),
    ):
        expire_enabled_activation(session, act, actor="TEST")
    assert uba1381.live_order_enabled is False
    assert uba1381.live_armed is False
    assert uba1380.live_order_enabled is True
    assert uba1380.live_armed is True


def test_stale_live_arm_revoked_without_active_activation(pause_ok) -> None:
    session = MagicMock()
    uba = _uba(uba_id=1380, broker="UPBIT")
    session.scalars.return_value = [uba]
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.broker.live_transition_service.LiveTradingTransitionService.peek_active",
            return_value=None,
        ),
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
        patch(
            _SCHEDULER_CTRL
        ),
    ):
        n = revoke_stale_live_without_activation(session, actor="SYSTEM")
    assert n == 1
    assert uba.live_order_enabled is False
    assert uba.live_armed is False
    assert uba.arm_token_hash is None
    assert audit.call_args.kwargs["detail"]["source"] == "STALE_NO_ACTIVE"


def test_scan_calls_expire_all_due() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.trading.live_session_expiry.expire_due_activations",
            return_value=1,
        ),
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService.expire_all_due",
            return_value=2,
        ) as arm_due,
        patch(
            "stock_platform.trading.live_session_expiry.revoke_stale_live_without_activation",
            return_value=0,
        ),
    ):
        out = scan_and_expire_live_sessions(session, actor="SYSTEM")
    arm_due.assert_called_once()
    assert out["activation_expired"] == 1
    assert out["arm_expired"] == 2


def test_expiry_runtime_interval_from_settings() -> None:
    rt = LiveSessionExpiryRuntime()
    st = rt.status()
    assert st["running"] is False
    assert 5.0 <= float(st["interval_seconds"]) <= 60.0


def test_outbox_dispatch_blocked_after_activation_expiry() -> None:
    """QUEUED LIVE outbox — Activation 없으면 adapter submit 0."""

    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
    )
    session.get.return_value = uba
    payload = {
        "environment": "LIVE",
        "broker_code": "UPBIT",
        "user_broker_account_id": 1380,
        "owner_user_id": 61,
    }
    adapter = MagicMock()
    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard.require_active",
            side_effect=PermissionError(
                "No active live trading transition approval"
            ),
        ),
    ):
        with pytest.raises(PermissionError, match="active live trading"):
            OrderOutboxWorker._assert_live_dispatch_allowed(
                session, payload, outbox_id=99
            )
    adapter.submit_order.assert_not_called()


def test_lazy_arm_expire_if_needed_still_live_off() -> None:
    """주기 job과 별도로 ARM TTL lazy expire_if_needed 유지."""

    session = MagicMock()
    uba = _uba(uba_id=1380, broker="UPBIT")
    uba.arm_expires_at = _now() - timedelta(seconds=5)
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
        patch(
            _SCHEDULER_CTRL
        ),
    ):
        expired = LiveArmService(session).expire_if_needed(1380)
    assert expired is True
    assert uba.live_order_enabled is False
    assert uba.live_armed is False
    assert uba.arm_token_hash is None


def test_default_arm_ttl_policy_unchanged() -> None:
    assert DEFAULT_ARM_TTL_SECONDS == 300
    from stock_platform.common.settings import LIVE_ACTIVATION_TTL_HOURS_MAX

    assert LIVE_ACTIVATION_TTL_HOURS_MAX == 72


def test_kiwoom_arm_clamp_regression() -> None:
    session = MagicMock()
    uba = _uba(uba_id=1381, broker="KIWOOM", armed=False)
    act = _activation(uba_id=1381, broker="KIWOOM", remaining_seconds=3600)
    svc = LiveArmService(session)
    with patch.object(svc, "_require_session_activation", return_value=act):
        effective, expires, _ = svc._clamp_arm_ttl(uba, 300, 300)
    assert effective == 300
    assert expires <= act.expires_at
