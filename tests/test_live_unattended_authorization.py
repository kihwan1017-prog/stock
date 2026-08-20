"""Unattended authorization — focused unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.live_unattended_authorization_service import (
    APPROVAL_MODEL_UNATTENDED_LEASE,
    CONFIRM_DISABLE,
    CONFIRM_ENABLE,
    SOURCE_ADMIN_UI,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_PROTECTIVE,
    LiveUnattendedAuthorizationService,
    LiveUnattendedError,
)


def test_enable_requires_exact_confirmation() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    with pytest.raises(LiveUnattendedError) as exc:
        svc.enable(
            1380,
            actor="admin",
            confirmation_text="yes",
            reason="test",
            source=SOURCE_ADMIN_UI,
        )
    assert exc.value.code == "CONFIRMATION_REQUIRED"


def test_status_dict_off_when_missing() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    uba = SimpleNamespace(broker_code="UPBIT")
    session.get.return_value = uba
    out = LiveUnattendedAuthorizationService(session).status_dict(1380)
    assert out["unattended_enabled"] is False
    assert out["status_code"] == "OFF"
    assert out["required_confirmation_text"] == CONFIRM_ENABLE
    assert out["requires_live_approval_phrase"] is False
    assert out["required_approval_phrase"] is None
    assert out["approval_model"] == APPROVAL_MODEL_UNATTENDED_LEASE


def test_enable_rejects_invalid_source() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    with pytest.raises(LiveUnattendedError) as exc:
        svc.enable(
            1380,
            actor="admin",
            confirmation_text=CONFIRM_ENABLE,
            reason="test",
            source="RANDOM",
        )
    assert exc.value.code == "INVALID_SOURCE"


def test_enable_fail_closed_when_gates_fail() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        user_id=7,
        is_active=True,
        live_order_enabled=True,
    )
    session.get.return_value = uba
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(
            svc,
            "evaluate_enable_gates",
            return_value={"ok": False, "blockers": ["ARM_OFF", "LIVE_OFF"]},
        ),
        patch.object(svc, "get_active", return_value=None),
        pytest.raises(LiveUnattendedError) as exc,
    ):
        svc.enable(
            1380,
            actor="admin",
            confirmation_text=CONFIRM_ENABLE,
            reason="test",
            source=SOURCE_ADMIN_UI,
        )
    assert exc.value.code == "SAFETY_GATES_FAILED"
    assert "ARM_OFF" in exc.value.message


def test_evaluate_enable_gates_requires_arm_and_live() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        user_id=7,
        is_active=True,
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=None,
        connection_status="CONNECTED",
        trading_paused=False,
    )
    session.get.return_value = uba
    session.scalar.return_value = 0

    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(
                allowed=True, code="UPBIT_FLAGS_OK", status="HEALTHY"
            ),
        ),
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as vault_cls,
        patch(
            "stock_platform.trading.runtime_control_gates.assert_recovery_ready",
            return_value={
                "trading_paused": False,
                "recovery_status": "SUCCESS",
            },
        ),
        patch(
            "stock_platform.trading.runtime_control_gates.assert_risk_account_not_paused",
            return_value={"account_paused": False},
        ),
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
        ) as kill_cls,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as lts_cls,
    ):
        vault_cls.return_value.status.return_value = SimpleNamespace(
            verification_status="VERIFIED"
        )
        kill_cls.return_value.is_active.return_value = False
        lts_cls.return_value.peek_active.return_value = None
        out = LiveUnattendedAuthorizationService(session).evaluate_enable_gates(
            1380
        )

    assert out["ok"] is False
    assert "LIVE_OFF" in out["blockers"]
    assert "ARM_OFF" in out["blockers"]
    assert "ACTIVATION_INACTIVE" in out["blockers"]


def test_enable_does_not_accept_live_approval_phrase_kwarg() -> None:
    """LIVE phrase는 enable 시그니처에서 제거됨 (계약 분리)."""

    import inspect

    params = inspect.signature(
        LiveUnattendedAuthorizationService.enable
    ).parameters
    assert "approval_phrase" not in params
    assert "source" in params


def test_is_entry_authorized_true_without_lease() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    assert (
        LiveUnattendedAuthorizationService(session).is_entry_authorized(1380)
        is True
    )


def test_is_entry_authorized_false_when_protective() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        enabled=True,
        status_code=STATUS_PROTECTIVE,
        entry_authorized=False,
        authorized_until=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.scalar.return_value = row
    assert (
        LiveUnattendedAuthorizationService(session).is_entry_authorized(1380)
        is False
    )


def test_expire_sets_protective_when_position() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        live_unattended_authorization_id=1,
        user_broker_account_id=1380,
        enabled=True,
        status_code=STATUS_ACTIVE,
        entry_authorized=True,
        protective_exit_authorized=True,
        authorized_until=datetime.now(timezone.utc) - timedelta(seconds=1),
        revoked_at=None,
        revoked_by=None,
        revoke_reason=None,
        updated_at=None,
    )
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "_has_open_position", return_value=True),
        patch.object(svc, "_fail_closed_on_expiry"),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
    ):
        svc._expire_authorization(row, actor="SYSTEM", reason="HORIZON_EXPIRED")
    assert row.status_code == STATUS_PROTECTIVE
    assert row.entry_authorized is False
    assert row.protective_exit_authorized is True
    assert row.enabled is True


def test_expire_full_when_flat() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        live_unattended_authorization_id=1,
        user_broker_account_id=1380,
        enabled=True,
        status_code=STATUS_ACTIVE,
        entry_authorized=True,
        protective_exit_authorized=True,
        authorized_until=datetime.now(timezone.utc) - timedelta(seconds=1),
        revoked_at=None,
        revoked_by=None,
        revoke_reason=None,
        updated_at=None,
    )
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "_has_open_position", return_value=False),
        patch.object(svc, "_fail_closed_on_expiry"),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
    ):
        svc._expire_authorization(row, actor="SYSTEM", reason="HORIZON_EXPIRED")
    assert row.status_code == STATUS_EXPIRED
    assert row.enabled is False


def test_disable_confirmation_constant() -> None:
    assert "24H UNATTENDED" in CONFIRM_ENABLE
    assert "DISABLE" in CONFIRM_DISABLE
