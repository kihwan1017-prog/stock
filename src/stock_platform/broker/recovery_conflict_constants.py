"""STEP 8-5-4 — Recovery Conflict 상수."""

from __future__ import annotations

from enum import StrEnum


class RecoveryConflictType(StrEnum):
    REMOTE_ORDER_NOT_FOUND_LOCALLY = "REMOTE_ORDER_NOT_FOUND_LOCALLY"
    ORDER_ACCOUNT_MISMATCH = "ORDER_ACCOUNT_MISMATCH"
    ORDER_MARKET_MISMATCH = "ORDER_MARKET_MISMATCH"
    ORDER_QUANTITY_MISMATCH = "ORDER_QUANTITY_MISMATCH"
    EXECUTION_MISMATCH = "EXECUTION_MISMATCH"
    BALANCE_MISMATCH = "BALANCE_MISMATCH"
    UNKNOWN_REMOTE_ORDER = "UNKNOWN_REMOTE_ORDER"


class RecoveryConflictReviewStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED_IMPORT = "APPROVED_IMPORT"
    IGNORED = "IGNORED"
    ON_HOLD = "ON_HOLD"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"
    REMOTE_DISAPPEARED = "REMOTE_DISAPPEARED"
    # STEP 8-14 — 검토 완료·이력 보존 (Import/Ignore 아님, Dashboard 미해결 제외)
    HISTORICAL_PRESERVED = "HISTORICAL_PRESERVED"


class RecoveryConflictResolution(StrEnum):
    IMPORT_INTERNAL_ORDER = "IMPORT_INTERNAL_ORDER"
    IGNORE_EXTERNAL_ORDER = "IGNORE_EXTERNAL_ORDER"
    KEEP_PAUSED = "KEEP_PAUSED"
    REMOTE_ORDER_CANCELLED = "REMOTE_ORDER_CANCELLED"
    DUPLICATE_INTERNAL_ORDER_FOUND = "DUPLICATE_INTERNAL_ORDER_FOUND"
    PRESERVE_HISTORY = "PRESERVE_HISTORY"


# Dashboard / Pause gate / Scheduler 재검토 대상
ACTIVE_REVIEW_STATUSES = frozenset(
    {
        RecoveryConflictReviewStatus.PENDING_REVIEW,
        RecoveryConflictReviewStatus.ON_HOLD,
    }
)

# upsert 시 동일 UUID Conflict 재생성 금지 (스냅샷만 갱신)
TERMINAL_REVIEW_STATUSES = frozenset(
    {
        RecoveryConflictReviewStatus.APPROVED_IMPORT,
        RecoveryConflictReviewStatus.IGNORED,
        RecoveryConflictReviewStatus.REMOTE_DISAPPEARED,
        RecoveryConflictReviewStatus.RESOLVED,
        RecoveryConflictReviewStatus.REJECTED,
        RecoveryConflictReviewStatus.HISTORICAL_PRESERVED,
    }
)

# Dashboard "Review Complete" 표시용
REVIEW_COMPLETE_STATUSES = frozenset(
    {
        RecoveryConflictReviewStatus.APPROVED_IMPORT,
        RecoveryConflictReviewStatus.IGNORED,
        RecoveryConflictReviewStatus.REMOTE_DISAPPEARED,
        RecoveryConflictReviewStatus.RESOLVED,
        RecoveryConflictReviewStatus.REJECTED,
        RecoveryConflictReviewStatus.HISTORICAL_PRESERVED,
    }
)

PAUSE_REASON_REMOTE_ONLY = "UPBIT_REMOTE_ONLY_ORDER_REVIEW"
ORDER_ORIGIN_RECOVERY_IMPORT = "RECOVERY_IMPORT"
