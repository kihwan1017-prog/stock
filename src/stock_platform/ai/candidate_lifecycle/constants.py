"""STEP 11-13 — Candidate Lifecycle constants.

Identity: candidate_id = strategy.candidate_result.result_id
Only promotion-created candidates (candidate_promotion_link) receive lifecycle rows.
"""

from __future__ import annotations

FINGERPRINT_VERSION = "fp-1.0.0"
HEALTH_VERSION = "health-1.0.0"
PROVENANCE_SCHEMA_VERSION = "prov-1.0.0"

REFERENCE_DISCLAIMER = (
    "AI 후보 수명주기는 Promotion Gateway를 통해 등록된 CandidateResult(result_id)에 대한 "
    "내부 참조·검증·만료·철회 관리이며, 자동 매매·전략 배포·주문 승인을 의미하지 않습니다."
)

LIFECYCLE_STATUS = frozenset(
    {
        "PROMOTED",
        "ACTIVE_REVIEW",
        "REVALIDATION_REQUIRED",
        "STALE",
        "SUPERSEDED",
        "EXPIRED",
        "REVOKED",
        "CANCELLED",
        "ARCHIVED",
        "REVOCATION_REQUESTED",
        "REVOCATION_BLOCKED",
        "REVALIDATING",
        "REVALIDATION_FAILED",
    }
)

HEALTH_STATUS = frozenset(
    {
        "HEALTHY",
        "WARNING",
        "STALE",
        "REVALIDATION_REQUIRED",
        "EXPIRED",
        "SUPERSEDED",
        "REVOKED",
        "UNKNOWN",
    }
)

HEALTH_PRIORITY: tuple[str, ...] = (
    "REVOKED",
    "SUPERSEDED",
    "EXPIRED",
    "REVALIDATION_REQUIRED",
    "STALE",
    "WARNING",
    "HEALTHY",
    "UNKNOWN",
)

REVALIDATION_STATUS = frozenset(
    {
        "REQUESTED",
        "RUNNING",
        "PASSED",
        "PASSED_WITH_WARNING",
        "FAILED",
        "CANCELLED",
    }
)

REVOCATION_STATUS = frozenset(
    {
        "REQUESTED",
        "VALIDATING",
        "BLOCKED",
        "APPROVED",
        "COMPLETED",
        "CANCELLED",
        "FAILED",
    }
)

SUPERSESSION_STATUS = frozenset({"ACTIVE", "COMPLETED", "CANCELLED"})

TERMINAL_LIFECYCLE_STATUSES = frozenset(
    {"REVOKED", "SUPERSEDED", "ARCHIVED", "CANCELLED"}
)

ACTIVE_REVOCATION_STATUSES = frozenset(
    {"REQUESTED", "VALIDATING", "BLOCKED", "APPROVED"}
)

# 상태 전이표 (스펙 §5 + REVOCATION_*/REVALIDATING 확장)
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PROMOTED": frozenset(
        {
            "ACTIVE_REVIEW",
            "REVALIDATION_REQUIRED",
            "STALE",
            "EXPIRED",
            "REVOKED",
            "SUPERSEDED",
            "REVOCATION_REQUESTED",
            "ARCHIVED",
        }
    ),
    "ACTIVE_REVIEW": frozenset(
        {
            "PROMOTED",
            "REVALIDATION_REQUIRED",
            "STALE",
            "EXPIRED",
            "REVOKED",
            "SUPERSEDED",
            "REVOCATION_REQUESTED",
            "ARCHIVED",
        }
    ),
    "REVALIDATION_REQUIRED": frozenset(
        {
            "PROMOTED",
            "STALE",
            "REVALIDATING",
            "EXPIRED",
            "REVOKED",
            "SUPERSEDED",
            "ARCHIVED",
        }
    ),
    "REVALIDATING": frozenset(
        {
            "PROMOTED",
            "REVALIDATION_REQUIRED",
            "STALE",
            "REVALIDATION_FAILED",
            "EXPIRED",
        }
    ),
    "REVALIDATION_FAILED": frozenset(
        {"REVALIDATION_REQUIRED", "STALE", "EXPIRED", "REVOKED", "ARCHIVED"}
    ),
    "STALE": frozenset(
        {
            "REVALIDATION_REQUIRED",
            "EXPIRED",
            "REVOKED",
            "SUPERSEDED",
            "ARCHIVED",
        }
    ),
    "EXPIRED": frozenset({"ARCHIVED", "REVOKED"}),
    "REVOCATION_REQUESTED": frozenset(
        {"REVOKED", "REVOCATION_BLOCKED", "PROMOTED", "ACTIVE_REVIEW", "ARCHIVED"}
    ),
    "REVOCATION_BLOCKED": frozenset(
        {"REVOCATION_REQUESTED", "PROMOTED", "ACTIVE_REVIEW", "ARCHIVED"}
    ),
    "REVOKED": frozenset({"ARCHIVED"}),
    "SUPERSEDED": frozenset({"ARCHIVED"}),
    "CANCELLED": frozenset({"ARCHIVED"}),
    "ARCHIVED": frozenset(),
}

AI_LIFECYCLE_PERMISSIONS = (
    "AI_CANDIDATE_LIFECYCLE_VIEW",
    "AI_CANDIDATE_LIFECYCLE_VALIDATE",
    "AI_CANDIDATE_LIFECYCLE_REVALIDATE",
    "AI_CANDIDATE_LIFECYCLE_EXPIRE",
    "AI_CANDIDATE_LIFECYCLE_REVOKE_REQUEST",
    "AI_CANDIDATE_LIFECYCLE_REVOKE_APPROVE",
    "AI_CANDIDATE_LIFECYCLE_ARCHIVE",
    "AI_CANDIDATE_LIFECYCLE_SUPERSEDE",
    "AI_CANDIDATE_LIFECYCLE_AUDIT",
)

CRYPTO_EXPIRY_HOURS = 48
KRX_EXPIRY_CALENDAR_DAYS = 7
