"""Focused tests for safe auto-recovery classification / circuit / shadow guard."""

from __future__ import annotations

from stock_platform.operation.startup_runtime_policy import (
    _detect_shadow_startup_listen_owner,
)
from stock_platform.trading.safe_auto_recovery.classification import (
    RecoveryClass,
    classify_incident,
)
from stock_platform.trading.safe_auto_recovery.circuit_breaker import (
    CircuitPolicy,
)


def test_class_a_activation_valid_live_off():
    r = classify_incident(
        primary_blocker="LIVE_OFF",
        blockers=["LIVE_OFF", "ARM_OFF"],
        failure_event_type="FAIL_CLOSED_RESTART",
        precheck={
            "stuck_count": 0,
            "ambiguous_count": 0,
            "unresolved_exit_count": 0,
            "recovery_conflict_count": 0,
            "broker_local": "PASS",
            "balance_sync": "READY",
            "position_recon": "PASS",
            "kill_active": False,
        },
        activation_active=True,
        unattended_active=True,
    )
    assert r.recovery_class == RecoveryClass.A
    assert r.auto_recover_allowed is True
    assert r.operator_required is False


def test_class_a_without_authorization_blocked():
    r = classify_incident(
        primary_blocker="LIVE_OFF",
        blockers=["LIVE_OFF"],
        precheck={
            "stuck_count": 0,
            "ambiguous_count": 0,
            "unresolved_exit_count": 0,
            "recovery_conflict_count": 0,
            "broker_local": "PASS",
            "balance_sync": "READY",
            "position_recon": "PASS",
            "kill_active": False,
        },
        activation_active=True,
        unattended_active=False,
    )
    assert r.recovery_class == RecoveryClass.C
    assert r.reason == "AUTHORIZATION_NOT_ACTIVE"


def test_class_c_ambiguous():
    r = classify_incident(
        primary_blocker="AMBIGUOUS_SUBMISSION",
        blockers=["AMBIGUOUS_SUBMISSION"],
        precheck={
            "stuck_count": 0,
            "ambiguous_count": 1,
            "unresolved_exit_count": 0,
            "recovery_conflict_count": 0,
            "broker_local": "PASS",
            "balance_sync": "READY",
            "position_recon": "PASS",
            "kill_active": False,
        },
        activation_active=True,
    )
    assert r.recovery_class == RecoveryClass.C
    assert r.auto_recover_allowed is False


def test_class_c_unresolved_exit():
    r = classify_incident(
        primary_blocker="LIVE_OFF",
        blockers=["LIVE_OFF"],
        precheck={
            "stuck_count": 0,
            "ambiguous_count": 0,
            "unresolved_exit_count": 1,
            "recovery_conflict_count": 0,
            "broker_local": "PASS",
            "balance_sync": "READY",
            "position_recon": "PASS",
            "kill_active": False,
        },
        activation_active=True,
    )
    assert r.recovery_class == RecoveryClass.C


def test_class_c_recovery_conflict():
    r = classify_incident(
        primary_blocker="LIVE_OFF",
        precheck={
            "stuck_count": 0,
            "ambiguous_count": 0,
            "unresolved_exit_count": 0,
            "recovery_conflict_count": 2,
            "broker_local": "PASS",
            "balance_sync": "READY",
            "position_recon": "PASS",
            "kill_active": False,
        },
        activation_active=True,
    )
    assert r.recovery_class == RecoveryClass.C


def test_class_b_zero_fill():
    r = classify_incident(
        primary_blocker="EXIT_PENDING_ZERO_FILL_STUCK",
        blockers=["EXIT_PENDING_ZERO_FILL_STUCK"],
        precheck={
            "stuck_count": 0,
            "ambiguous_count": 0,
            "unresolved_exit_count": 0,
            "recovery_conflict_count": 0,
            "broker_local": "PASS",
            "balance_sync": "READY",
            "position_recon": "PASS",
            "kill_active": False,
        },
        activation_active=True,
        unattended_active=True,
    )
    assert r.recovery_class == RecoveryClass.B
    assert r.requires_broker_reconcile is True


def test_class_c_circuit_open():
    r = classify_incident(
        primary_blocker="LIVE_OFF",
        precheck={
            "stuck_count": 0,
            "ambiguous_count": 0,
            "unresolved_exit_count": 0,
            "recovery_conflict_count": 0,
            "broker_local": "PASS",
            "balance_sync": "READY",
            "position_recon": "PASS",
            "kill_active": False,
        },
        circuit_open=True,
        activation_active=True,
    )
    assert r.recovery_class == RecoveryClass.C
    assert r.reason == "RECOVERY_CIRCUIT_OPEN"


def test_class_a_requires_activation():
    r = classify_incident(
        primary_blocker="LIVE_OFF",
        precheck={
            "stuck_count": 0,
            "ambiguous_count": 0,
            "unresolved_exit_count": 0,
            "recovery_conflict_count": 0,
            "broker_local": "PASS",
            "balance_sync": "READY",
            "position_recon": "PASS",
            "kill_active": False,
        },
        activation_active=False,
        unattended_active=True,
    )
    assert r.recovery_class == RecoveryClass.C
    assert r.reason == "ACTIVATION_NOT_ACTIVE"


def test_circuit_policy_defaults():
    p = CircuitPolicy()
    assert p.max_attempts == 3
    assert p.window_seconds == 3600


def test_shadow_guard_returns_dict():
    out = _detect_shadow_startup_listen_owner()
    assert "is_shadow" in out
    assert "self_pid" in out or out.get("reason")