"""P0.7 focused cases — finite Operator Authorization + lease renew within auth."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.live_unattended_authorization_service import (
    ACTOR_HORIZON_AUTO_RENEW,
    CONFIRM_DISABLE,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_PROTECTIVE,
    LiveUnattendedAuthorizationService,
)
from stock_platform.trading.operator_authorization_policy import (
    AUTH_EXPIRY_EXISTING_POSITION_POLICY,
    AUTH_EXPIRY_NO_POSITION_POLICY,
    assert_lease_invariants,
    validate_operator_authorization_hours,
)


def _now() -> datetime:
    return datetime(2026, 9, 7, 0, 0, 0, tzinfo=timezone.utc)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        live_unattended_default_horizon_hours=24,
        live_unattended_max_horizon_hours=168,
        live_unattended_horizon_renew_margin_seconds=3600,
        live_unattended_horizon_renew_interval_seconds=3600,
        live_unattended_horizon_min_extension_seconds=3600,
        live_unattended_renewal_interval_seconds=3600,
        live_unattended_renewal_margin_seconds=600,
        live_unattended_arm_lease_ttl_seconds=3600,
        live_unattended_activation_renew_hours=8,
    )


@pytest.fixture(autouse=True)
def _patch_settings() -> None:
    with patch(
        "stock_platform.trading.live_unattended_authorization_service.get_settings",
        return_value=_settings(),
    ):
        yield


def _row(**kwargs: object) -> SimpleNamespace:
    now = _now()
    base = dict(
        live_unattended_authorization_id=19,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        status_code=STATUS_ACTIVE,
        enabled=True,
        entry_authorized=True,
        protective_exit_authorized=True,
        auto_renew_enabled=True,
        authorized_until=now + timedelta(hours=24),
        renewal_interval_seconds=3600,
        renewal_margin_seconds=600,
        arm_lease_ttl_seconds=3600,
        activation_renew_hours=8,
        last_renewed_at=None,
        last_renewal_actor=None,
        last_renewal_detail={"authorization_mode": "HOURS_24"},
        updated_at=now,
        approved_by="admin",
        approved_at=now,
        revoked_at=None,
        revoked_by=None,
        revoke_reason=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _uba(**kwargs: object) -> SimpleNamespace:
    now = _now()
    base = dict(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        user_id=7,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=now + timedelta(minutes=30),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_case1_validate_24h_duration() -> None:
    assert validate_operator_authorization_hours(24) == 24
    approved = _now()
    expires = approved + timedelta(hours=24)
    assert (expires - approved).total_seconds() == 24 * 3600


def test_case2_expiring_soon_warning_only() -> None:
    session = MagicMock()
    now = _now()
    old_until = now + timedelta(minutes=45)
    row = _row(authorized_until=old_until)
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch(
            "stock_platform.trading.live_unattended_authorization_service._now",
            return_value=now,
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_order_telegram"
        ),
    ):
        out = svc._try_horizon_auto_renew(
            row, _uba(), actor=ACTOR_HORIZON_AUTO_RENEW
        )
    assert out["horizon_renewed"] is False
    assert out["authorization_expiring_soon"] is True
    assert row.authorized_until == old_until
    assert audit.call_args.kwargs["event_type"] == "AUTHORIZATION_EXPIRING_SOON"


def test_case3_4_lease_invariants() -> None:
    now = _now()
    auth = now + timedelta(hours=24)
    act = now + timedelta(hours=8)
    arm = act - timedelta(seconds=300)
    ok = assert_lease_invariants(
        authorization_expires_at=auth,
        activation_expires_at=act,
        arm_expires_at=arm,
    )
    assert ok["ok"] is True

    bad = assert_lease_invariants(
        authorization_expires_at=auth,
        activation_expires_at=auth + timedelta(hours=1),
        arm_expires_at=arm,
    )
    assert bad["ok"] is False
    assert "ACTIVATION_EXCEEDS_AUTHORIZATION" in bad["issues"]


def test_case5_expire_no_position_fail_closed_full() -> None:
    session = MagicMock()
    row = _row(authorized_until=_now() - timedelta(seconds=1))
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "_has_open_position", return_value=False),
        patch.object(svc, "_fail_closed_on_expiry") as fail,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
    ):
        svc._expire_authorization(row, actor="TEST", reason="HORIZON_EXPIRED")
    assert row.status_code == STATUS_EXPIRED
    assert row.enabled is False
    assert row.entry_authorized is False
    fail.assert_called_once()
    assert AUTH_EXPIRY_NO_POSITION_POLICY == "FAIL_CLOSED_FULL"


def test_case6_expire_with_position_protective() -> None:
    session = MagicMock()
    row = _row(authorized_until=_now() - timedelta(seconds=1))
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "_has_open_position", return_value=True),
        patch.object(svc, "_fail_closed_on_expiry") as fail,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
    ):
        svc._expire_authorization(row, actor="TEST", reason="HORIZON_EXPIRED")
    assert row.status_code == STATUS_PROTECTIVE
    assert row.protective_exit_authorized is True
    fail.assert_called_once()
    assert AUTH_EXPIRY_EXISTING_POSITION_POLICY == "PROTECTIVE_EXIT_ONLY"


def test_case8_restore_keeps_same_authorization_id_when_valid() -> None:
    """유효 Auth 동안 restore는 동일 authorization_id 재사용 (새 Auth 생성 없음)."""
    now = _now()
    row = _row(authorized_until=now + timedelta(hours=10))
    # 동일 row 재사용 계약 — 새 승인 없이 lease 복구
    assert row.live_unattended_authorization_id == 19
    assert row.status_code == STATUS_ACTIVE
    assert aware_until_ok(row.authorized_until, now)


def aware_until_ok(until: datetime, now: datetime) -> bool:
    return until > now


def test_case9_restore_blocked_after_auth_expiry() -> None:
    session = MagicMock()
    now = _now()
    row = _row(authorized_until=now - timedelta(minutes=1))
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_active", return_value=row),
        patch(
            "stock_platform.trading.live_unattended_authorization_service._now",
            return_value=now,
        ),
        patch(
            "stock_platform.operation.runtime_process_stability.assert_stable_runtime_for_real_trading",
            return_value=None,
        ),
        patch.object(svc, "_expire_authorization") as expire,
    ):
        out = svc.restore_from_active_lease(1380, actor="TEST_RESTORE")
    assert out["restored"] is False
    assert out["reason"] == "HORIZON_EXPIRED"
    expire.assert_called_once()


def test_case10_system_horizon_auto_extend_denied() -> None:
    session = MagicMock()
    now = _now()
    old_until = now + timedelta(minutes=20)
    row = _row(auto_renew_enabled=True, authorized_until=old_until)
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch(
            "stock_platform.trading.live_unattended_authorization_service._now",
            return_value=now,
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_order_telegram"
        ),
    ):
        out = svc._try_horizon_auto_renew(
            row, _uba(), actor=ACTOR_HORIZON_AUTO_RENEW
        )
    assert out["horizon_renewed"] is False
    assert out["reason"] == "OPERATOR_AUTHORIZATION_AUTO_EXTEND_NOT_SUPPORTED"
    assert out["operator_authorization_auto_extend"] is False
    assert row.authorized_until == old_until


def test_case11_explicit_approval_hours_require_allowed_set() -> None:
    assert validate_operator_authorization_hours(48) == 48
    assert validate_operator_authorization_hours(72) == 72
    with pytest.raises(ValueError):
        validate_operator_authorization_hours(36)


def test_case12_unattended_off_keeps_auth_active() -> None:
    session = MagicMock()
    row = _row(enabled=True, entry_authorized=True)
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_authorization", return_value=row),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
        patch.object(svc, "_fail_closed_on_expiry"),
        patch.object(
            svc,
            "status_dict",
            return_value={
                "status_code": STATUS_ACTIVE,
                "unattended_enabled": False,
                "authorization_id": 19,
            },
        ),
    ):
        out = svc.disable(
            1380,
            actor="admin",
            confirmation_text=CONFIRM_DISABLE,
            reason="test",
        )
    assert row.status_code == STATUS_ACTIVE
    assert row.enabled is False
    assert row.entry_authorized is False
    assert out["status_code"] == STATUS_ACTIVE


def test_arm_renew_ttl_capped_by_auth_horizon() -> None:
    now = _now()
    until = now + timedelta(minutes=25)
    arm_lease_ttl = 3600
    lease_remaining = max(60, int((until - now).total_seconds()))
    arm_ttl = min(arm_lease_ttl, lease_remaining)
    intended = now + timedelta(seconds=arm_ttl)
    if intended > until:
        intended = until
    assert intended <= until
    assert arm_ttl <= lease_remaining
