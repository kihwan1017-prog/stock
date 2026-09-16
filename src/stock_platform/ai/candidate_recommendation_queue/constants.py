"""STEP 11-11 — Candidate Recommendation Queue constants.

Safety: APPROVED_FOR_CONSIDERATION = 기존 Candidate 등록 여부를 다음 Gateway에서
검토할 수 있음. 후보 등록·매매·주문 승인이 아님.
"""

from __future__ import annotations

QUEUE_ENGINE_VERSION = "11.11.0"
ELIGIBILITY_VERSION = "elig-1.0.0"
REVIEW_FORMULA_VERSION = "rubric-1.0.0"

REFERENCE_DISCLAIMER = (
    "AI 후보 추천 검토 큐는 기존 Candidate 등록 여부를 검토하기 위한 내부 업무 큐이며, "
    "실제 매수·매도 추천이나 주문 승인이 아닙니다."
)
CONSIDERATION_LABEL = "기존 후보 등록 검토 가능"
APPROVED_WITH_WARNINGS_LABEL = "경고 조건부 후보 등록 검토 가능"

SOURCE_TYPES = frozenset({"CANDIDATE_ASSESSMENT", "CANDIDATE_CONSENSUS"})

QUEUE_STATUS = frozenset(
    {
        "DRAFT",
        "QUEUED",
        "ASSIGNED",
        "UNDER_REVIEW",
        "MORE_INFORMATION_REQUIRED",
        "APPROVED_FOR_CONSIDERATION",
        "APPROVED_WITH_WARNINGS",
        "REJECTED",
        "ON_HOLD",
        "EXPIRED",
        "WITHDRAWN",
        "SUPERSEDED",
        "NOT_ELIGIBLE",
        "ARCHIVED",
    }
)

ACTIVE_QUEUE_STATUSES = frozenset(
    {
        "DRAFT",
        "QUEUED",
        "ASSIGNED",
        "UNDER_REVIEW",
        "MORE_INFORMATION_REQUIRED",
        "ON_HOLD",
        "APPROVED_FOR_CONSIDERATION",
        "APPROVED_WITH_WARNINGS",
    }
)

PRIORITY = frozenset({"LOW", "NORMAL", "HIGH", "URGENT"})

REVIEW_STATUS = frozenset({"DRAFT", "SUBMITTED", "AMENDED", "WITHDRAWN"})

DECISION = frozenset(
    {
        "PENDING",
        "APPROVED_FOR_CONSIDERATION",
        "APPROVED_WITH_WARNINGS",
        "REJECTED",
        "ON_HOLD",
        "MORE_INFORMATION_REQUIRED",
        "NOT_ELIGIBLE",
        "EXPIRED",
        "WITHDRAWN",
    }
)

DECISION_LABELS = {
    "APPROVED_FOR_CONSIDERATION": CONSIDERATION_LABEL,
    "APPROVED_WITH_WARNINGS": APPROVED_WITH_WARNINGS_LABEL,
}

ASSIGNMENT_STATUS = frozenset({"ACTIVE", "ACCEPTED", "COMPLETED", "CANCELLED"})

RESOLUTION_STATUS = frozenset({"OPEN", "RESOLVED", "DISMISSED", "ACKNOWLEDGED"})

RECOMMENDATION_SCOPES = frozenset({"CONSIDERATION_ONLY", "REFERENCE_ONLY"})

FINDING_TYPES = frozenset(
    {
        "SOURCE_STALE",
        "SOURCE_SUPERSEDED",
        "INSUFFICIENT_EVIDENCE",
        "LOW_EVIDENCE_QUALITY",
        "LOW_DATA_QUALITY",
        "LOW_PROVIDER_DIVERSITY",
        "HIGH_DISAGREEMENT",
        "CRITICAL_RISK",
        "MINORITY_RISK_UNRESOLVED",
        "CITATION_WARNING",
        "NUMERIC_MISMATCH",
        "ENTITY_MISMATCH",
        "TIME_HORIZON_MISMATCH",
        "DUPLICATE_QUEUE",
        "EXISTING_CANDIDATE_CONFLICT",
        "POLICY_WARNING",
        "SAFETY_VIOLATION",
        "TRADING_LANGUAGE_DETECTED",
        "OTHER",
    }
)

SEVERITIES = frozenset({"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"})

SCORE_MIN = 0
SCORE_MAX = 100
RUBRIC_MIN = 0
RUBRIC_MAX = 5

KRX_DEFAULT_EXPIRY_HOURS = 24
KRX_MAX_EXPIRY_HOURS = 72
CRYPTO_DEFAULT_EXPIRY_HOURS = 12
CRYPTO_MAX_EXPIRY_HOURS = 48

QUEUEABLE_ASSESSMENT_STATUSES = frozenset(
    {
        "VALIDATED",
        "VALIDATED_WITH_WARNINGS",
        "REVIEW_APPROVED",
    }
)

QUEUEABLE_CONSENSUS_STATUSES = frozenset(
    {
        "VALIDATED",
        "VALIDATED_WITH_WARNINGS",
        "CALCULATED",
        "REVIEW_APPROVED",
    }
)

APPROVED_SOURCE_REVIEW = frozenset({"APPROVED", "APPROVED_WITH_WARNINGS"})

TERMINAL_QUEUE_STATUSES = frozenset(
    {
        "APPROVED_FOR_CONSIDERATION",
        "APPROVED_WITH_WARNINGS",
        "REJECTED",
        "WITHDRAWN",
        "EXPIRED",
        "SUPERSEDED",
        "NOT_ELIGIBLE",
        "ARCHIVED",
    }
)

MAX_BATCH_CREATE = 100

AI_QUEUE_PERMISSIONS = (
    "AI_CANDIDATE_QUEUE_VIEW",
    "AI_CANDIDATE_QUEUE_CREATE",
    "AI_CANDIDATE_QUEUE_ASSIGN",
    "AI_CANDIDATE_QUEUE_REVIEW",
    "AI_CANDIDATE_QUEUE_DECIDE",
    "AI_CANDIDATE_QUEUE_OVERRIDE",
    "AI_CANDIDATE_QUEUE_AUDIT",
    "AI_CANDIDATE_QUEUE_BATCH",
    "AI_CANDIDATE_QUEUE_EXPIRE",
    "AI_CANDIDATE_QUEUE_REQUEUE",
)

# DB 컬럼과 동일 키 (migration review table)
RUBRIC_WEIGHTS = {
    "eligibility_score": 0.20,
    "analytical_quality_score": 0.15,
    "evidence_quality_score": 0.15,
    "risk_awareness_score": 0.20,
    "consistency_score": 0.10,
    "safety_score": 0.20,
}

MIN_OVERALL_FOR_CONSIDERATION = 3.0
MIN_SAFETY_FOR_CONSIDERATION = 3.0

FORBIDDEN_TRADING_KEYS = frozenset(
    {
        "buy",
        "sell",
        "hold",
        "recommendation",
        "recommended_action",
        "execute",
        "order",
        "submit_order",
        "target_price",
        "entry_price",
        "stop_loss",
        "take_profit",
        "position_size",
        "candidate_approved",
        "candidate_rank",
        "live",
        "arm",
    }
)
