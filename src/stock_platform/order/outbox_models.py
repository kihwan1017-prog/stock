from enum import StrEnum


class OutboxEventType(StrEnum):
    SUBMIT_ORDER = "SUBMIT_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"
    REPLACE_ORDER = "REPLACE_ORDER"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    RETRY = "RETRY"
    DONE = "DONE"
    FAILED = "FAILED"
    # STEP 8-5-22 — Fencing / Ambiguous (자동 재전송 금지)
    AMBIGUOUS = "AMBIGUOUS"
    MANUAL_REVIEW = "MANUAL_REVIEW"
