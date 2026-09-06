"""Operator Authorization policy + Class A/B authorization gate tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from stock_platform.trading.operator_authorization_policy import (
    AUTH_EXPIRY_EXISTING_POSITION_POLICY,
    OPERATOR_AUTHORIZATION_ALLOWED_HOURS,
    assert_lease_invariants,
    authorization_active_from_unattended,
    build_operator_authorization_view,
    validate_operator_authorization_hours,
)
from stock_platform.trading.safe_auto_recovery.classification import (
    RecoveryClass,
    classify_incident,
)


def _precheck_ok() -> dict:
    return {
        "stuck_count": 0,
        "ambiguous_count": 0,
        "unresolved_exit_count": 0,
        "recovery_conflict_count": 0,
        "broker_local": "PASS",
        "balance_sync": "READY",
        "position_recon": "PASS",
        "kill_active": False,
    }


def test_allowed_hours_24_48_72():
    assert validate_operator_authorization_hours(24) == 24
    assert validate_operator_authorization_hours(48) == 48
    assert validate_operator_authorization_hours(72) == 72
    assert OPERATOR_AUTHORIZATION_ALLOWED_HOURS == (24, 48, 72)


def test_invalid_hours_rejected():
    with pytest.raises(ValueError):
        validate_operator_authorization_hours(12)
    with pytest.raises(ValueError):
        validate_operator_authorization_hours(96)


def test_authorization_active_detection():
    assert authorization_active_from_unattended({"unattended_enabled": True})
    assert not authorization_active_from_unattended({"status_code": "OFF"})


def test_lease_invariants_pass():
    now = datetime.now(timezone.utc)
    auth = now + timedelta(hours=24)
    act = now + timedelta(hours=8)
    arm = act - timedelta(seconds=60)
    out = assert_lease_invariants(
        authorization_expires_at=auth,
        activation_expires_at=act,
        arm_expires_at=arm,
        safety_margin_seconds=60,
    )
    assert out["ok"] is True


def test_lease_invariants_arm_exceeds_activation():
    now = datetime.now(timezone.utc)
    act = now + timedelta(hours=1)
    arm = act + timedelta(minutes=5)
    out = assert_lease_invariants(
        authorization_expires_at=now + timedelta(hours=24),
        activation_expires_at=act,
        arm_expires_at=arm,
    )
    assert out["ok"] is False
    assert "ARM_EXCEEDS_ACTIVATION" in out["issues"]


def test_class_a_requires_authorization():
    r = classify_incident(
        primary_blocker="LIVE_OFF",
        blockers=["LIVE_OFF", "ARM_OFF"],
        precheck=_precheck_ok(),
        activation_active=True,
        unattended_active=False,
    )
    assert r.recovery_class == RecoveryClass.C
    assert r.reason == "AUTHORIZATION_NOT_ACTIVE"
    assert r.auto_recover_allowed is False


def test_class_a_with_authorization_and_activation():
    r = classify_incident(
        primary_blocker="LIVE_OFF",
        blockers=["LIVE_OFF", "ARM_OFF"],
        precheck=_precheck_ok(),
        activation_active=True,
        unattended_active=True,
    )
    assert r.recovery_class == RecoveryClass.A
    assert r.auto_recover_allowed is True


def test_class_b_requires_authorization():
    r = classify_incident(
        primary_blocker="EXIT_PENDING_ZERO_FILL_STUCK",
        blockers=["EXIT_PENDING_ZERO_FILL_STUCK"],
        precheck=_precheck_ok(),
        activation_active=True,
        unattended_active=False,
    )
    assert r.recovery_class == RecoveryClass.C
    assert r.reason == "AUTHORIZATION_NOT_ACTIVE"


def test_class_b_with_authorization():
    r = classify_incident(
        primary_blocker="EXIT_PENDING_ZERO_FILL_STUCK",
        blockers=["EXIT_PENDING_ZERO_FILL_STUCK"],
        precheck=_precheck_ok(),
        activation_active=True,
        unattended_active=True,
    )
    assert r.recovery_class == RecoveryClass.B
    assert r.auto_recover_allowed is True


def test_class_c_blocks_even_with_authorization():
    r = classify_incident(
        primary_blocker="AMBIGUOUS_SUBMISSION",
        blockers=["AMBIGUOUS_SUBMISSION"],
        precheck=_precheck_ok(),
        activation_active=True,
        unattended_active=True,
    )
    assert r.recovery_class == RecoveryClass.C
    assert r.auto_recover_allowed is False


def test_circuit_open_priority():
    r = classify_incident(
        primary_blocker="LIVE_OFF",
        precheck=_precheck_ok(),
        circuit_open=True,
        activation_active=True,
        unattended_active=True,
    )
    assert r.recovery_class == RecoveryClass.C
    assert r.reason == "RECOVERY_CIRCUIT_OPEN"


def test_kill_switch_in_precheck_blocks():
    pre = _precheck_ok()
    pre["kill_active"] = True
    r = classify_incident(
        primary_blocker="LIVE_OFF",
        precheck=pre,
        activation_active=True,
        unattended_active=True,
    )
    assert r.recovery_class == RecoveryClass.C


def test_operator_authorization_view_and_policy_constant():
    view = build_operator_authorization_view(
        {
            "unattended_enabled": True,
            "status_code": "ACTIVE",
            "authorization_id": 9,
            "authorized_until": "2099-01-01T00:00:00+00:00",
            "remaining_seconds": 3600,
            "approved_by": "admin",
            "auto_renew_enabled": True,
        }
    )
    assert view["active"] is True
    assert view["sot"] == "operation.live_unattended_authorization"
    assert AUTH_EXPIRY_EXISTING_POSITION_POLICY == "PROTECTIVE_EXIT_ONLY"
