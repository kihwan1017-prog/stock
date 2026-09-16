"""Recovery Conflict 선택 해제·Resume 사전점검 상수."""

from __future__ import annotations

from enum import StrEnum


class AdminConflictResolution(StrEnum):
    """관리자 선택 Resolution — Clear 일괄 Ignore와 분리."""

    IGNORE_WITH_AUDIT = "IGNORE_WITH_AUDIT"
    PRESERVE_REMOTE_HISTORY = "PRESERVE_REMOTE_HISTORY"
    APPROVE_IMPORT = "APPROVE_IMPORT"
    REJECT_RESOLUTION = "REJECT_RESOLUTION"


# IGNORE_WITH_AUDIT 허용에 필요한 conflict_type
IGNORE_ELIGIBLE_TYPES = frozenset(
    {
        "REMOTE_ORDER_NOT_FOUND_LOCALLY",
    }
)

# 종료로 간주하는 원격 상태
TERMINAL_REMOTE_STATUSES = frozenset(
    {
        "done",
        "cancel",
        "cancelled",
        "canceled",
    }
)

OPEN_REMOTE_STATUSES = frozenset({"wait", "watch"})
