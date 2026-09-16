"""Safe auto-recovery classification — Class A/B/C (fail-closed)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RecoveryClass(StrEnum):
    A = "A"  # transient ops — auto recover after precheck
    B = "B"  # broker-canonical reconcile then recover
    C = "C"  # operator required — never auto LIVE/ARM ON


class RecoveryEligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    OPERATOR_REQUIRED = "OPERATOR_REQUIRED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    LOCKED = "LOCKED"


# Class C hard codes — any match → no auto LIVE/ARM restore
CLASS_C_CODES = frozenset(
    {
        "KILL_SWITCH_ACTIVE",
        "BROKER_UNKNOWN",
        "AMBIGUOUS_SUBMISSION",
        "AMBIGUOUS_OUTBOX",
        "UNRESOLVED_EXIT",
        "RECOVERY_CONFLICT",
        "BALANCE_MISMATCH",
        "POSITION_MISMATCH",
        "DUPLICATE_ORDER_RISK",
        "CREDENTIAL_INVALID",
        "CONNECTION_DOWN",
        "UNEXPECTED_POSITION",
        "RISK_VIOLATION",
        "ACCOUNT_RECONCILIATION_FAILED",
        "SYSTEM_FAILURE_UNSAFE",
    }
)

# Class B — needs broker reconcile first
CLASS_B_CODES = frozenset(
    {
        "BROKER_DONE_LOCAL_PENDING",
        "BROKER_CANCEL_LOCAL_PENDING",
        "MISSING_BROKER_UUID",
        "PARTIAL_FILL_LAG",
        "EXIT_PENDING_ZERO_FILL_STUCK",
        "BROKER_FILLED_LOCAL_ZERO",
    }
)

# Class A — restart/component/feed/lease transient
CLASS_A_CODES = frozenset(
    {
        "FAIL_CLOSED_RESTART",
        "SHADOW_STARTUP_FAIL_CLOSED",
        "LIVE_OFF",
        "ARM_OFF",
        "ARM_OFF_OR_EXPIRED",
        "RUNTIME_COMPONENT_STOPPED",
        "EXECUTION_STACK_DOWN",
        "LIVE_EXECUTION_RUNNER_NOT_RUNNING",
        "HEARTBEAT_STALE",
        "FEED_STALE_RECOVERED",
        "ACCOUNT_SYNC_TRANSIENT",
        "INTERNAL_LEASE_EXPIRED",
        "ARM_RENEWAL_NEEDED",
    }
)


@dataclass
class ClassificationResult:
    recovery_class: RecoveryClass
    eligibility: RecoveryEligibility
    reason_codes: list[str] = field(default_factory=list)
    primary_code: str | None = None
    reason: str = ""
    requires_broker_reconcile: bool = False
    auto_recover_allowed: bool = False
    operator_required: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recovery_class": str(self.recovery_class),
            "eligibility": str(self.eligibility),
            "reason_codes": list(self.reason_codes),
            "primary_code": self.primary_code,
            "reason": self.reason,
            "requires_broker_reconcile": self.requires_broker_reconcile,
            "auto_recover_allowed": self.auto_recover_allowed,
            "operator_required": self.operator_required,
            "details": self.details,
        }


def classify_incident(
    *,
    primary_blocker: str | None,
    blockers: list[str] | None = None,
    failure_event_type: str | None = None,
    precheck: dict[str, Any] | None = None,
    circuit_open: bool = False,
    unattended_active: bool = False,
    activation_active: bool = False,
) -> ClassificationResult:
    """안전등급 분류. fail-open 금지 — 애매하면 Class C."""

    codes = [str(c).upper() for c in (blockers or []) if c]
    if primary_blocker:
        codes.insert(0, str(primary_blocker).upper())
    if failure_event_type:
        codes.append(str(failure_event_type).upper())
    # unique preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    primary = ordered[0] if ordered else None
    pre = precheck or {}

    # Hard unsafe gates from precheck
    unsafe_flags = [
        k
        for k, ok in {
            "stuck_zero": int(pre.get("stuck_count") or 0) == 0,
            "ambiguous_zero": int(pre.get("ambiguous_count") or 0) == 0,
            "unresolved_exit_zero": int(pre.get("unresolved_exit_count") or 0)
            == 0,
            "recovery_conflict_zero": int(pre.get("recovery_conflict_count") or 0)
            == 0,
            "broker_local_pass": str(pre.get("broker_local") or "").upper()
            == "PASS",
            "balance_ready": str(pre.get("balance_sync") or "").upper()
            == "READY",
            "position_pass": str(pre.get("position_recon") or "PASS").upper()
            == "PASS",
            "no_kill": not bool(pre.get("kill_active")),
        }.items()
        if not ok
    ]

    if circuit_open:
        return ClassificationResult(
            recovery_class=RecoveryClass.C,
            eligibility=RecoveryEligibility.CIRCUIT_OPEN,
            reason_codes=ordered,
            primary_code=primary,
            reason="RECOVERY_CIRCUIT_OPEN",
            operator_required=True,
            auto_recover_allowed=False,
            details={"unsafe_flags": unsafe_flags},
        )

    if any(c in CLASS_C_CODES for c in ordered) or unsafe_flags:
        return ClassificationResult(
            recovery_class=RecoveryClass.C,
            eligibility=RecoveryEligibility.OPERATOR_REQUIRED,
            reason_codes=ordered,
            primary_code=primary,
            reason="CLASS_C_OR_PRECHECK_UNSAFE",
            operator_required=True,
            auto_recover_allowed=False,
            details={"unsafe_flags": unsafe_flags},
        )

    # Operator Authorization SoT = unattended lease ACTIVE
    authorization_active = bool(unattended_active)

    if any(c in CLASS_B_CODES for c in ordered):
        if not authorization_active:
            return ClassificationResult(
                recovery_class=RecoveryClass.C,
                eligibility=RecoveryEligibility.OPERATOR_REQUIRED,
                reason_codes=ordered,
                primary_code=primary,
                reason="AUTHORIZATION_NOT_ACTIVE",
                requires_broker_reconcile=True,
                auto_recover_allowed=False,
                operator_required=True,
                details={
                    "activation_active": activation_active,
                    "authorization_active": authorization_active,
                    "note": "Class B requires Operator Authorization ACTIVE",
                },
            )
        return ClassificationResult(
            recovery_class=RecoveryClass.B,
            eligibility=RecoveryEligibility.ELIGIBLE,
            reason_codes=ordered,
            primary_code=primary,
            reason="BROKER_CANONICAL_RECONCILE_THEN_RESTORE",
            requires_broker_reconcile=True,
            auto_recover_allowed=True,
            operator_required=False,
            details={
                "activation_active": activation_active,
                "unattended_active": unattended_active,
                "authorization_active": authorization_active,
            },
        )

    # Class A: Authorization ACTIVE + Activation ACTIVE + precheck PASS
    class_a_hit = any(c in CLASS_A_CODES for c in ordered) or primary in {
        "LIVE_OFF",
        "ARM_OFF",
        "ARM_OFF_OR_EXPIRED",
    }
    if (
        class_a_hit
        and authorization_active
        and activation_active
        and not unsafe_flags
    ):
        return ClassificationResult(
            recovery_class=RecoveryClass.A,
            eligibility=RecoveryEligibility.ELIGIBLE,
            reason_codes=ordered,
            primary_code=primary,
            reason="CLASS_A_AUTHORIZATION_AND_ACTIVATION_VALID",
            auto_recover_allowed=True,
            operator_required=False,
            details={
                "activation_active": activation_active,
                "unattended_active": unattended_active,
                "authorization_active": authorization_active,
                "note": (
                    "Operator Authorization (unattended lease) ACTIVE required "
                    "for Class A auto-recovery"
                ),
            },
        )

    if class_a_hit and not authorization_active:
        return ClassificationResult(
            recovery_class=RecoveryClass.C,
            eligibility=RecoveryEligibility.OPERATOR_REQUIRED,
            reason_codes=ordered,
            primary_code=primary,
            reason="AUTHORIZATION_NOT_ACTIVE",
            operator_required=True,
            auto_recover_allowed=False,
            details={
                "activation_active": activation_active,
                "authorization_active": False,
            },
        )

    if class_a_hit and not activation_active:
        return ClassificationResult(
            recovery_class=RecoveryClass.C,
            eligibility=RecoveryEligibility.OPERATOR_REQUIRED,
            reason_codes=ordered,
            primary_code=primary,
            reason="ACTIVATION_NOT_ACTIVE",
            operator_required=True,
            auto_recover_allowed=False,
        )

    # Unknown → Class C
    return ClassificationResult(
        recovery_class=RecoveryClass.C,
        eligibility=RecoveryEligibility.OPERATOR_REQUIRED,
        reason_codes=ordered,
        primary_code=primary,
        reason="UNCLASSIFIED_FAIL_CLOSED",
        operator_required=True,
        auto_recover_allowed=False,
    )
