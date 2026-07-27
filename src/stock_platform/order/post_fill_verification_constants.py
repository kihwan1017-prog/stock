"""STEP 8-8A — Post-Fill Verification 상태 상수."""

from __future__ import annotations

from enum import StrEnum


class PostFillVerifyStatus(StrEnum):
    PENDING = "PENDING"
    WAITING_SNAPSHOT = "WAITING_SNAPSHOT"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


TERMINAL_STATUSES = frozenset(
    {
        PostFillVerifyStatus.VERIFIED.value,
        PostFillVerifyStatus.MISMATCH.value,
        PostFillVerifyStatus.FAILED.value,
        PostFillVerifyStatus.EXPIRED.value,
    }
)

ACTIVE_STATUSES = frozenset(
    {
        PostFillVerifyStatus.PENDING.value,
        PostFillVerifyStatus.WAITING_SNAPSHOT.value,
        PostFillVerifyStatus.VERIFYING.value,
    }
)

# Audit 이벤트
POST_FILL_VERIFY_PENDING = "POST_FILL_VERIFY_PENDING"
POST_FILL_SNAPSHOT_STALE = "POST_FILL_SNAPSHOT_STALE"
POST_FILL_RETRY_SCHEDULED = "POST_FILL_RETRY_SCHEDULED"
POST_FILL_VERIFIED = "POST_FILL_VERIFIED"
POST_FILL_MISMATCH = "POST_FILL_MISMATCH"
POST_FILL_VERIFY_EXPIRED = "POST_FILL_VERIFY_EXPIRED"
POST_FILL_VERIFY_FAILED = "POST_FILL_VERIFY_FAILED"
POST_FILL_BROKER_DOWN_DELAY = "POST_FILL_BROKER_DOWN_DELAY"
