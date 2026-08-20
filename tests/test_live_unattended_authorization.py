"""Unattended authorization — focused unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.live_unattended_authorization_service import (
    CONFIRM_DISABLE,
    CONFIRM_ENABLE,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_PROTECTIVE,
    LiveUnattendedAuthorizationService,
    LiveUnattendedError,
)


def test_enable_requires_confirmation() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    with pytest.raises(LiveUnattendedError) as exc:
        svc.enable(
            1380,
            actor="admin",
            confirmation_text="yes",
            approval_phrase="x",
            reason="test",
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
    assert out["required_approval_phrase"] == "ENABLE UPBIT LIVE TRADING"


def test_approval_phrase_rejects_confirmation_text() -> None:
    """confirmation과 LIVE phrase 혼동 방지 — 검증 약화 없음."""

    assert (
        LiveUnattendedAuthorizationService._approval_phrase_matches(
            CONFIRM_ENABLE,
            "ENABLE UPBIT LIVE TRADING",
        )
        is False
    )
    assert (
        LiveUnattendedAuthorizationService._approval_phrase_matches(
            "ENABLE UPBIT LIVE TRADING",
            "ENABLE UPBIT LIVE TRADING",
        )
        is True
    )


def test_enable_rejects_wrong_live_phrase() -> None:
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
        patch.object(svc, "get_active", return_value=None),
        pytest.raises(LiveUnattendedError) as exc,
    ):
        svc.enable(
            1380,
            actor="admin",
            confirmation_text=CONFIRM_ENABLE,
            approval_phrase=CONFIRM_ENABLE,  # 흔한 혼동
            reason="test",
        )
    assert exc.value.code == "INVALID_APPROVAL_PHRASE"
    assert "ENABLE UPBIT LIVE TRADING" in exc.value.message


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
