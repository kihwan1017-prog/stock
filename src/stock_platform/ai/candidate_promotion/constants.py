"""STEP 11-12 — Candidate Promotion Gateway constants.

Safety: Queue 승인·Promotion Request·Dry-run ≠ strategy.candidate 등록.
Commit 완료 시에만 CandidateRun/Result INSERT (AI_REVIEW_PROMOTION).
"""

from __future__ import annotations

PROMOTION_ENGINE_VERSION = "11.12.0"
ELIGIBILITY_VERSION = "elig-1.0.0"
MAPPING_VERSION = "mapping-1.0.0"
SCORE_FORMULA_VERSION = "promotion-score-1.0.0"
DRY_RUN_VERSION = "dry-run-1.0.0"
PROMOTION_RUN_TYPE = "AI_REVIEW_PROMOTION"
MAX_BATCH = 20

REFERENCE_DISCLAIMER = (
    "AI Candidate Promotion Gateway는 검토 완료 Queue를 기존 Candidate Engine에 "
    "수동 등록하는 내부 게이트웨이이며, 전략·매매·주문·Runtime·Scheduler를 "
    "실행하지 않습니다. Promotion 완료는 Candidate 등록만 수행합니다."
)

PROMOTABLE_QUEUE_STATUSES = frozenset(
    {"APPROVED_FOR_CONSIDERATION", "APPROVED_WITH_WARNINGS"}
)

PROMOTION_STATUS = frozenset(
    {
        "DRAFT",
        "VALIDATING",
        "VALIDATED",
        "VALIDATED_WITH_WARNINGS",
        "DRY_RUN_READY",
        "DRY_RUN_COMPLETED",
        "FIRST_APPROVAL_PENDING",
        "FIRST_APPROVED",
        "FINAL_APPROVAL_PENDING",
        "FINAL_APPROVED",
        "COMMIT_PENDING",
        "COMMITTING",
        "COMPLETED",
        "BLOCKED",
        "REJECTED",
        "CANCELLED",
        "EXPIRED",
        "STALE",
        "FAILED",
        "ROLLBACK_REQUIRED",
        "ROLLED_BACK",
        "ARCHIVED",
    }
)

ACTIVE_PROMOTION_STATUSES = frozenset(
    {
        "DRAFT",
        "VALIDATING",
        "VALIDATED",
        "VALIDATED_WITH_WARNINGS",
        "DRY_RUN_READY",
        "DRY_RUN_COMPLETED",
        "FIRST_APPROVAL_PENDING",
        "FIRST_APPROVED",
        "FINAL_APPROVAL_PENDING",
        "FINAL_APPROVED",
        "COMMIT_PENDING",
        "COMMITTING",
    }
)

TERMINAL_PROMOTION_STATUSES = frozenset(
    {
        "COMPLETED",
        "BLOCKED",
        "REJECTED",
        "CANCELLED",
        "EXPIRED",
        "STALE",
        "FAILED",
        "ROLLBACK_REQUIRED",
        "ROLLED_BACK",
        "ARCHIVED",
    }
)

VALIDATION_TYPES = frozenset(
    {
        "ELIGIBILITY",
        "SOURCE",
        "QUEUE",
        "EXPIRATION",
        "FINDING",
        "INSTRUMENT",
        "EXISTING_CANDIDATE",
        "MAPPING",
        "SIDE_EFFECT",
        "COMMIT_PRECONDITION",
    }
)

VALIDATION_STATUS = frozenset({"PASS", "FAIL", "WARN", "SKIP"})

APPROVAL_STAGES = frozenset({"FIRST", "FINAL", "COMMIT_CONFIRM"})

APPROVAL_STATUS = frozenset({"PENDING", "APPROVED", "REJECTED", "REVOKED", "EXPIRED"})

SOURCE_TYPES = frozenset({"CANDIDATE_ASSESSMENT", "CANDIDATE_CONSENSUS"})

SEVERITIES = frozenset({"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"})

ROLLBACK_STATUS = frozenset({"NONE", "ROLLED_BACK", "BLOCKED"})

SCORE_SOURCE_TYPE = "AI_REVIEW_PROMOTION_SCORE"

# Queue rubric 0~5 → 0~1 정규화
RUBRIC_SCALE_MAX = 5.0

# AI confidence 단독 고점 방지 — 기여 상한 (0~1)
CONFIDENCE_CONTRIBUTION_CAP = 0.60

DEFAULT_PROMOTION_EXPIRY_HOURS = 72

AI_PROMOTION_PERMISSIONS = (
    "AI_CANDIDATE_PROMOTION_VIEW",
    "AI_CANDIDATE_PROMOTION_CREATE",
    "AI_CANDIDATE_PROMOTION_VALIDATE",
    "AI_CANDIDATE_PROMOTION_DRY_RUN",
    "AI_CANDIDATE_PROMOTION_FIRST_APPROVE",
    "AI_CANDIDATE_PROMOTION_FINAL_APPROVE",
    "AI_CANDIDATE_PROMOTION_COMMIT",
    "AI_CANDIDATE_PROMOTION_CANCEL",
    "AI_CANDIDATE_PROMOTION_ROLLBACK",
    "AI_CANDIDATE_PROMOTION_OVERRIDE",
    "AI_CANDIDATE_PROMOTION_AUDIT",
    "AI_CANDIDATE_PROMOTION_BATCH",
)

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
