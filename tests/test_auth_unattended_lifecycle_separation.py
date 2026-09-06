"""Auth vs Unattended lifecycle separation — focused tests (실주문 0)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.live_unattended_authorization_service import (
    CONFIRM_DISABLE,
    CONFIRM_ENABLE,
    CONFIRM_REVOKE_AUTHORIZATION,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_REVOKED,
    LiveUnattendedAuthorizationService,
    LiveUnattendedError,
)
from stock_platform.trading.operator_authorization_policy import (
    authorization_active_from_unattended,
)


def _row(**kwargs):
    now = datetime.now(timezone.utc)
    base = dict(
        live_unattended_authorization_id=99,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        status_code=STATUS_ACTIVE,
        enabled=True,
        entry_authorized=True,
        protective_exit_authorized=True,
        authorized_until=now + timedelta(hours=12),
        renewal_interval_seconds=3600,
        renewal_margin_seconds=600,
        arm_lease_ttl_seconds=3600,
        activation_renew_hours=8,
        max_authorization_horizon_hours=72,
        last_renewal_detail={"authorization_mode": "HOURS_24"},
        last_renewed_at=None,
        last_renewal_actor=None,
        auto_renew_enabled=True,
        approved_by="admin",
        approved_at=now,
        revoked_at=None,
        revoked_by=None,
        revoke_reason=None,
        updated_at=now,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_authorization_active_when_unattended_off_but_status_active():
    assert authorization_active_from_unattended(
        {
            "status_code": "ACTIVE",
            "remaining_seconds": 3600,
            "unattended_enabled": False,
            "entry_lease_active": False,
            "operator_authorization_active": True,
        }
    )


def test_disable_keeps_authorization_active():
    session = MagicMock()
    row = _row()
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_authorization", return_value=row),
        patch.object(
            svc,
            "status_dict",
            return_value={
                "status_code": STATUS_ACTIVE,
                "unattended_enabled": False,
                "operator_authorization_active": True,
                "remaining_seconds": 1000,
            },
        ),
        patch.object(svc, "_fail_closed_on_expiry") as fail_closed,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ) as audit,
    ):
        out = svc.disable(
            1380,
            actor="admin",
            confirmation_text=CONFIRM_DISABLE,
            reason="maintenance_stop",
            fail_closed=True,
        )
    assert row.status_code == STATUS_ACTIVE
    assert row.enabled is False
    assert row.entry_authorized is False
    assert row.revoked_at is None
    fail_closed.assert_called_once()
    events = [c.kwargs.get("event_type") for c in audit.call_args_list]
    assert "UNATTENDED_DISABLED" in events
    assert "UNATTENDED_AUTHORIZATION_REVOKED" not in events
    assert "OPERATOR_AUTHORIZATION_REVOKED" not in events
    assert out["status_code"] == STATUS_ACTIVE


def test_explicit_revoke_sets_revoked():
    session = MagicMock()
    row = _row(enabled=False, entry_authorized=False)
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_authorization", return_value=row),
        patch.object(
            svc,
            "status_dict",
            return_value={"status_code": STATUS_REVOKED},
        ),
        patch.object(svc, "_fail_closed_on_expiry"),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ) as audit,
    ):
        svc.revoke_authorization(
            1380,
            actor="admin",
            confirmation_text=CONFIRM_REVOKE_AUTHORIZATION,
            reason="operator_explicit_revoke",
        )
    assert row.status_code == STATUS_REVOKED
    assert row.revoked_at is not None
    events = [c.kwargs.get("event_type") for c in audit.call_args_list]
    assert "OPERATOR_AUTHORIZATION_REVOKED" in events


def test_enable_resumes_same_active_authorization():
    session = MagicMock()
    now = datetime.now(timezone.utc)
    row = _row(
        enabled=False,
        entry_authorized=False,
        authorized_until=now + timedelta(hours=10),
    )
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        user_id=7,
        is_active=True,
    )
    session.get.return_value = uba
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_authorization", return_value=row),
        patch.object(
            svc,
            "evaluate_enable_gates",
            return_value={"ok": True, "blockers": [], "live": "ON", "arm": "ON"},
        ),
        patch.object(
            svc,
            "status_dict",
            return_value={
                "status_code": STATUS_ACTIVE,
                "unattended_enabled": True,
                "resumed": True,
            },
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.get_settings"
        ) as gs,
    ):
        gs.return_value = SimpleNamespace(
            live_unattended_default_horizon_hours=24,
            live_unattended_max_horizon_hours=72,
            live_unattended_renewal_interval_seconds=3600,
            live_unattended_renewal_margin_seconds=600,
            live_unattended_arm_lease_ttl_seconds=3600,
            live_unattended_activation_renew_hours=8,
        )
        out = svc.enable(
            1380,
            actor="admin",
            confirmation_text=CONFIRM_ENABLE,
            reason="resume_after_maintenance",
            horizon_hours=24,
        )
    assert row.enabled is True
    assert row.entry_authorized is True
    assert row.status_code == STATUS_ACTIVE
    assert out.get("resumed_existing_authorization") is True
    events = [c.kwargs.get("event_type") for c in audit.call_args_list]
    assert "UNATTENDED_ENABLED" in events


def test_renew_skipped_when_unattended_execution_off():
    session = MagicMock()
    row = _row(enabled=False, entry_authorized=False)
    svc = LiveUnattendedAuthorizationService(session)
    with patch.object(svc, "get_active", return_value=row):
        out = svc.renew_due_for_uba(1380)
    assert out["renewed"] is False
    assert out["reason"] == "UNATTENDED_EXECUTION_OFF"


def test_expire_does_not_set_revoked_fields():
    session = MagicMock()
    row = _row()
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "_fail_closed_on_expiry"),
        patch.object(svc, "_has_open_position", return_value=False),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ) as audit,
    ):
        svc._expire_authorization(row, actor="SYSTEM", reason="HORIZON_EXPIRED")
    assert row.status_code == STATUS_EXPIRED
    assert row.revoked_at is None
    assert row.revoke_reason is None
    events = [c.kwargs.get("event_type") for c in audit.call_args_list]
    assert "OPERATOR_AUTHORIZATION_EXPIRED" in events
    assert "OPERATOR_AUTHORIZATION_REVOKED" not in events


def test_revoke_requires_confirmation():
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    with pytest.raises(LiveUnattendedError) as ei:
        svc.revoke_authorization(
            1380,
            actor="admin",
            confirmation_text="DISABLE 24H UNATTENDED",
            reason="wrong confirm",
        )
    assert ei.value.code == "CONFIRMATION_REQUIRED"
