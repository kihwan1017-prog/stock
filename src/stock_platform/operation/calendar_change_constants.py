"""STEP 8-5-11 — KRX Calendar Change Request / Special Session 상수."""

from __future__ import annotations

from enum import StrEnum


class CalendarChangeStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    APPLIED_WITH_SCHEDULER_ERROR = "APPLIED_WITH_SCHEDULER_ERROR"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    CONFLICT = "CONFLICT"


class CalendarChangeType(StrEnum):
    FULL_DAY_CLOSE = "FULL_DAY_CLOSE"
    OPEN_DAY_OVERRIDE = "OPEN_DAY_OVERRIDE"
    DELAYED_OPEN = "DELAYED_OPEN"
    EARLY_CLOSE = "EARLY_CLOSE"
    SPECIAL_SESSION = "SPECIAL_SESSION"
    SESSION_TIME_CHANGE = "SESSION_TIME_CHANGE"
    HOLIDAY_NAME_CHANGE = "HOLIDAY_NAME_CHANGE"
    SOURCE_CORRECTION = "SOURCE_CORRECTION"
    VERIFICATION_CHANGE = "VERIFICATION_CHANGE"
    ROLLBACK = "ROLLBACK"


class CalendarSourceType(StrEnum):
    CURATED_KR_HOLIDAY = "CURATED_KR_HOLIDAY"
    GENERATED_WEEKDAY = "GENERATED_WEEKDAY"
    KRX_OFFICIAL_NOTICE = "KRX_OFFICIAL_NOTICE"
    GOVERNMENT_NOTICE = "GOVERNMENT_NOTICE"
    ADMIN_MANUAL = "ADMIN_MANUAL"
    EMERGENCY_ADMIN = "EMERGENCY_ADMIN"


ACTIVE_CHANGE_STATUSES = frozenset(
    {
        CalendarChangeStatus.DRAFT.value,
        CalendarChangeStatus.PENDING_REVIEW.value,
        CalendarChangeStatus.APPROVED.value,
        CalendarChangeStatus.CONFLICT.value,
    }
)

TERMINAL_CHANGE_STATUSES = frozenset(
    {
        CalendarChangeStatus.APPLIED.value,
        CalendarChangeStatus.APPLIED_WITH_SCHEDULER_ERROR.value,
        CalendarChangeStatus.REJECTED.value,
        CalendarChangeStatus.CANCELLED.value,
        CalendarChangeStatus.SUPERSEDED.value,
        CalendarChangeStatus.FAILED.value,
    }
)

# 동적 Job Key: exchange + market_date + job_type + calendar_revision
# STEP 8-5-13 — Snapshot/AI/Cutoff 포함 (Timeline Offset 기준)
CALENDAR_JOB_TYPES = frozenset(
    {
        "PREOPEN_RECOVERY",
        "POST_CLOSE_RECOVERY",
        "MARKET_OPEN",
        "MARKET_CLOSE",
        "NEW_ENTRY_CUTOFF",
        "SNAPSHOT",
        "AI_ANALYSIS",
    }
)
