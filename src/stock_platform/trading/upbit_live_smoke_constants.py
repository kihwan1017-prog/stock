"""STEP 8-9A — Upbit Live Smoke 내부/Broker 상태 및 Audit 상수."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

CONFIRMATION_TEXT = "UPBIT-LIVE-ONE-ORDER"
CONFIRMATION_TEXT_BUY = "UPBIT LIVE BUY CONFIRM"
CONFIRMATION_TEXT_SELL = "UPBIT LIVE SELL CONFIRM"


def confirmation_text_for_side(side: str) -> str:
    """매수/매도별 최종 확인문구."""

    return (
        CONFIRMATION_TEXT_BUY
        if str(side or "").upper() == "BUY"
        else CONFIRMATION_TEXT_SELL
    )


DEFAULT_SMOKE_AMOUNT = Decimal("5000")
MAX_SMOKE_AMOUNT = Decimal("10000")
DEFAULT_ALLOWLIST = ("KRW-BTC", "KRW-ETH", "KRW-XRP")

# Controlled smoke audit (Secret/JWT 미저장)
LIVE_ORDER_SMOKE_PREFLIGHTED = "LIVE_ORDER_SMOKE_PREFLIGHTED"
LIVE_ORDER_SMOKE_PREVIEWED = "LIVE_ORDER_SMOKE_PREVIEWED"
LIVE_ORDER_SMOKE_ORDER_TESTED = "LIVE_ORDER_SMOKE_ORDER_TESTED"
LIVE_ORDER_SMOKE_CONFIRMED = "LIVE_ORDER_SMOKE_CONFIRMED"
LIVE_ORDER_SMOKE_SUBMITTED = "LIVE_ORDER_SMOKE_SUBMITTED"
LIVE_ORDER_SMOKE_FILLED = "LIVE_ORDER_SMOKE_FILLED"
LIVE_ORDER_SMOKE_RECONCILED = "LIVE_ORDER_SMOKE_RECONCILED"
LIVE_ORDER_SMOKE_FAILED = "LIVE_ORDER_SMOKE_FAILED"

ORDER_TEST_TTL_SECONDS = 60


class InternalStatus(StrEnum):
    """내부 처리 상태 — Outbox 완료 ≠ Broker 확정."""

    CREATED = "CREATED"
    PREFLIGHT_RUNNING = "PREFLIGHT_RUNNING"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    READY = "READY"
    EXECUTION_REQUESTED = "EXECUTION_REQUESTED"
    OUTBOX_PENDING = "OUTBOX_PENDING"
    OUTBOX_DISPATCHING = "OUTBOX_DISPATCHING"
    BROKER_SUBMISSION_PENDING = "BROKER_SUBMISSION_PENDING"
    BROKER_TRACKING = "BROKER_TRACKING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCEL_TRACKING = "CANCEL_TRACKING"
    POST_FILL_VERIFYING = "POST_FILL_VERIFYING"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"  # DB/내부 예외 — 실주문 미전송
    FAILED_CLOSED = "FAILED_CLOSED"
    DRY_RUN_COMPLETED = "DRY_RUN_COMPLETED"
    # 레거시 호환 alias (status_code에 남을 수 있음)
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    QUEUED = "QUEUED"  # trading_order + outbox commit 완료 (브로커 전송 전)
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    VERIFIED = "VERIFIED"


# 기존 이름 유지
LiveValidationRunStatus = InternalStatus


class BrokerOrderStatus(StrEnum):
    """Broker 확정 상태 — Outbox만으로 ACCEPTED/COMPLETED 금지."""

    NOT_SUBMITTED = "NOT_SUBMITTED"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    ACCEPTED = "ACCEPTED"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    PARTIALLY_FILLED_CANCELED = "PARTIALLY_FILLED_CANCELED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


TERMINAL_BROKER_STATUSES = frozenset(
    {
        BrokerOrderStatus.FILLED.value,
        BrokerOrderStatus.CANCELED.value,
        BrokerOrderStatus.REJECTED.value,
        BrokerOrderStatus.PARTIALLY_FILLED_CANCELED.value,
    }
)

# 예외 처리 시 UNKNOWN으로 덮어쓰지 않을 내부 terminal 상태
TERMINAL_INTERNAL_STATUSES = frozenset(
    {
        InternalStatus.REJECTED.value,
        InternalStatus.FILLED.value,
        InternalStatus.CANCELED.value,
        InternalStatus.FAILED.value,
        InternalStatus.FAILED_CLOSED.value,
        InternalStatus.COMPLETED.value,
        InternalStatus.DRY_RUN_COMPLETED.value,
        InternalStatus.VERIFIED.value,
        InternalStatus.PREFLIGHT_FAILED.value,
    }
)

TRACKABLE_BROKER_STATUSES = frozenset(
    {
        BrokerOrderStatus.SUBMISSION_UNKNOWN.value,
        BrokerOrderStatus.ACCEPTED.value,
        BrokerOrderStatus.OPEN.value,
        BrokerOrderStatus.PARTIALLY_FILLED.value,
        BrokerOrderStatus.CANCEL_PENDING.value,
        BrokerOrderStatus.UNKNOWN.value,
    }
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    InternalStatus.CREATED.value: frozenset(
        {
            InternalStatus.PREFLIGHT_RUNNING.value,
            InternalStatus.PREFLIGHT_FAILED.value,
            InternalStatus.READY.value,
            InternalStatus.FAILED.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.EXECUTION_REQUESTED.value,
        }
    ),
    InternalStatus.PREFLIGHT_RUNNING.value: frozenset(
        {
            InternalStatus.PREFLIGHT_FAILED.value,
            InternalStatus.READY.value,
            InternalStatus.FAILED_CLOSED.value,
        }
    ),
    InternalStatus.READY.value: frozenset(
        {
            InternalStatus.EXECUTION_REQUESTED.value,
            InternalStatus.DRY_RUN_COMPLETED.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.PREFLIGHT_FAILED.value,
        }
    ),
    InternalStatus.EXECUTION_REQUESTED.value: frozenset(
        {
            InternalStatus.OUTBOX_PENDING.value,
            InternalStatus.QUEUED.value,
            InternalStatus.ORDER_SUBMITTED.value,
            InternalStatus.REJECTED.value,
            InternalStatus.UNKNOWN.value,
            InternalStatus.FAILED.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.BROKER_SUBMISSION_PENDING.value,
        }
    ),
    InternalStatus.OUTBOX_PENDING.value: frozenset(
        {
            InternalStatus.OUTBOX_DISPATCHING.value,
            InternalStatus.BROKER_SUBMISSION_PENDING.value,
            InternalStatus.BROKER_TRACKING.value,
            InternalStatus.ORDER_SUBMITTED.value,
            InternalStatus.ORDER_ACCEPTED.value,
            InternalStatus.UNKNOWN.value,
            InternalStatus.FAILED.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.REJECTED.value,
            InternalStatus.MANUAL_REVIEW_REQUIRED.value,
            # 미전송 주문 내부 폐기 — 브로커 미호출 terminal
            InternalStatus.CANCELED.value,
        }
    ),
    InternalStatus.QUEUED.value: frozenset(
        {
            InternalStatus.OUTBOX_PENDING.value,
            InternalStatus.OUTBOX_DISPATCHING.value,
            InternalStatus.BROKER_SUBMISSION_PENDING.value,
            InternalStatus.BROKER_TRACKING.value,
            InternalStatus.ORDER_SUBMITTED.value,
            InternalStatus.ORDER_ACCEPTED.value,
            InternalStatus.FAILED.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.UNKNOWN.value,
            InternalStatus.MANUAL_REVIEW_REQUIRED.value,
            InternalStatus.CANCELED.value,
        }
    ),
    InternalStatus.FAILED.value: frozenset(
        {
            InternalStatus.FAILED_CLOSED.value,
        }
    ),
    InternalStatus.OUTBOX_DISPATCHING.value: frozenset(
        {
            InternalStatus.BROKER_SUBMISSION_PENDING.value,
            InternalStatus.BROKER_TRACKING.value,
            InternalStatus.UNKNOWN.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.REJECTED.value,
        }
    ),
    InternalStatus.BROKER_SUBMISSION_PENDING.value: frozenset(
        {
            InternalStatus.BROKER_TRACKING.value,
            InternalStatus.UNKNOWN.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.REJECTED.value,
            InternalStatus.ORDER_SUBMITTED.value,
        }
    ),
    InternalStatus.ORDER_SUBMITTED.value: frozenset(
        {
            InternalStatus.BROKER_TRACKING.value,
            InternalStatus.ORDER_ACCEPTED.value,
            InternalStatus.PARTIALLY_FILLED.value,
            InternalStatus.FILLED.value,
            InternalStatus.CANCEL_REQUESTED.value,
            InternalStatus.CANCELED.value,
            InternalStatus.REJECTED.value,
            InternalStatus.UNKNOWN.value,
            InternalStatus.FAILED_CLOSED.value,
        }
    ),
    InternalStatus.BROKER_TRACKING.value: frozenset(
        {
            InternalStatus.ORDER_ACCEPTED.value,
            InternalStatus.PARTIALLY_FILLED.value,
            InternalStatus.FILLED.value,
            InternalStatus.CANCEL_REQUESTED.value,
            InternalStatus.CANCEL_TRACKING.value,
            InternalStatus.POST_FILL_VERIFYING.value,
            InternalStatus.CANCELED.value,
            InternalStatus.REJECTED.value,
            InternalStatus.UNKNOWN.value,
            InternalStatus.MANUAL_REVIEW_REQUIRED.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.COMPLETED.value,
        }
    ),
    InternalStatus.ORDER_ACCEPTED.value: frozenset(
        {
            InternalStatus.BROKER_TRACKING.value,
            InternalStatus.PARTIALLY_FILLED.value,
            InternalStatus.FILLED.value,
            InternalStatus.CANCEL_REQUESTED.value,
            InternalStatus.CANCELED.value,
            InternalStatus.UNKNOWN.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.POST_FILL_VERIFYING.value,
        }
    ),
    InternalStatus.PARTIALLY_FILLED.value: frozenset(
        {
            InternalStatus.FILLED.value,
            InternalStatus.CANCEL_REQUESTED.value,
            InternalStatus.CANCEL_TRACKING.value,
            InternalStatus.CANCELED.value,
            InternalStatus.POST_FILL_VERIFYING.value,
            InternalStatus.UNKNOWN.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.BROKER_TRACKING.value,
        }
    ),
    InternalStatus.FILLED.value: frozenset(
        {
            InternalStatus.POST_FILL_VERIFYING.value,
            InternalStatus.VERIFIED.value,
            InternalStatus.COMPLETED.value,
            InternalStatus.FAILED_CLOSED.value,
        }
    ),
    InternalStatus.CANCEL_REQUESTED.value: frozenset(
        {
            InternalStatus.CANCEL_TRACKING.value,
            InternalStatus.CANCELED.value,
            InternalStatus.UNKNOWN.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.FILLED.value,
            InternalStatus.MANUAL_REVIEW_REQUIRED.value,
        }
    ),
    InternalStatus.CANCEL_TRACKING.value: frozenset(
        {
            InternalStatus.CANCELED.value,
            InternalStatus.FILLED.value,
            InternalStatus.PARTIALLY_FILLED.value,
            InternalStatus.POST_FILL_VERIFYING.value,
            InternalStatus.UNKNOWN.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.MANUAL_REVIEW_REQUIRED.value,
            InternalStatus.COMPLETED.value,
        }
    ),
    InternalStatus.CANCELED.value: frozenset(
        {
            InternalStatus.COMPLETED.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.POST_FILL_VERIFYING.value,
        }
    ),
    InternalStatus.POST_FILL_VERIFYING.value: frozenset(
        {
            InternalStatus.VERIFIED.value,
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.COMPLETED.value,
            InternalStatus.MANUAL_REVIEW_REQUIRED.value,
        }
    ),
    InternalStatus.VERIFIED.value: frozenset(
        {InternalStatus.COMPLETED.value}
    ),
    InternalStatus.REJECTED.value: frozenset(
        {
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.COMPLETED.value,
        }
    ),
    InternalStatus.UNKNOWN.value: frozenset(
        {
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.MANUAL_REVIEW_REQUIRED.value,
            InternalStatus.BROKER_TRACKING.value,
            InternalStatus.COMPLETED.value,
        }
    ),
    InternalStatus.MANUAL_REVIEW_REQUIRED.value: frozenset(
        {
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.COMPLETED.value,
            InternalStatus.BROKER_TRACKING.value,
        }
    ),
    InternalStatus.PREFLIGHT_FAILED.value: frozenset(
        {
            InternalStatus.FAILED_CLOSED.value,
            InternalStatus.COMPLETED.value,
        }
    ),
    InternalStatus.FAILED_CLOSED.value: frozenset(),
    InternalStatus.COMPLETED.value: frozenset(),
    InternalStatus.DRY_RUN_COMPLETED.value: frozenset(),
}

# Audit
UPBIT_LIVE_SMOKE_PREFLIGHT_STARTED = "UPBIT_LIVE_SMOKE_PREFLIGHT_STARTED"
UPBIT_LIVE_SMOKE_PREFLIGHT_PASSED = "UPBIT_LIVE_SMOKE_PREFLIGHT_PASSED"
UPBIT_LIVE_SMOKE_PREFLIGHT_FAILED = "UPBIT_LIVE_SMOKE_PREFLIGHT_FAILED"
UPBIT_LIVE_SMOKE_EXECUTION_REQUESTED = "UPBIT_LIVE_SMOKE_EXECUTION_REQUESTED"
UPBIT_LIVE_SMOKE_ORDER_SUBMITTED = "UPBIT_LIVE_SMOKE_ORDER_SUBMITTED"
UPBIT_LIVE_SMOKE_ORDER_ACCEPTED = "UPBIT_LIVE_SMOKE_ORDER_ACCEPTED"
UPBIT_LIVE_SMOKE_ORDER_FILLED = "UPBIT_LIVE_SMOKE_ORDER_FILLED"
UPBIT_LIVE_SMOKE_ORDER_PARTIAL = "UPBIT_LIVE_SMOKE_ORDER_PARTIAL"
UPBIT_LIVE_SMOKE_ORDER_CANCELED = "UPBIT_LIVE_SMOKE_ORDER_CANCELED"
UPBIT_LIVE_SMOKE_ORDER_REJECTED = "UPBIT_LIVE_SMOKE_ORDER_REJECTED"
UPBIT_LIVE_SMOKE_ORDER_UNKNOWN = "UPBIT_LIVE_SMOKE_ORDER_UNKNOWN"
UPBIT_LIVE_SMOKE_POST_FILL_VERIFIED = "UPBIT_LIVE_SMOKE_POST_FILL_VERIFIED"
UPBIT_LIVE_SMOKE_FAILED_CLOSED = "UPBIT_LIVE_SMOKE_FAILED_CLOSED"
UPBIT_LIVE_SMOKE_COMPLETED = "UPBIT_LIVE_SMOKE_COMPLETED"

UPBIT_LIVE_SMOKE_OUTBOX_CREATED = "UPBIT_LIVE_SMOKE_OUTBOX_CREATED"
UPBIT_LIVE_SMOKE_OUTBOX_DISPATCHED = "UPBIT_LIVE_SMOKE_OUTBOX_DISPATCHED"
UPBIT_LIVE_SMOKE_ONE_SHOT_GRANT_ISSUED = (
    "UPBIT_LIVE_SMOKE_ONE_SHOT_GRANT_ISSUED"
)
UPBIT_LIVE_SMOKE_ONE_SHOT_GRANT_CONSUMED = (
    "UPBIT_LIVE_SMOKE_ONE_SHOT_GRANT_CONSUMED"
)
UPBIT_LIVE_SMOKE_ONE_SHOT_DISPATCH_ALLOWED = (
    "UPBIT_LIVE_SMOKE_ONE_SHOT_DISPATCH_ALLOWED"
)
UPBIT_LIVE_SMOKE_BROKER_SUBMISSION_STARTED = (
    "UPBIT_LIVE_SMOKE_BROKER_SUBMISSION_STARTED"
)
UPBIT_LIVE_SMOKE_BROKER_SUBMISSION_TIMEOUT = (
    "UPBIT_LIVE_SMOKE_BROKER_SUBMISSION_TIMEOUT"
)
UPBIT_LIVE_SMOKE_BROKER_ORDER_FOUND_BY_IDENTIFIER = (
    "UPBIT_LIVE_SMOKE_BROKER_ORDER_FOUND_BY_IDENTIFIER"
)
UPBIT_LIVE_SMOKE_BROKER_ACCEPTED = "UPBIT_LIVE_SMOKE_BROKER_ACCEPTED"
UPBIT_LIVE_SMOKE_BROKER_OPEN = "UPBIT_LIVE_SMOKE_BROKER_OPEN"
UPBIT_LIVE_SMOKE_BROKER_PARTIAL = "UPBIT_LIVE_SMOKE_BROKER_PARTIAL"
UPBIT_LIVE_SMOKE_BROKER_FILLED = "UPBIT_LIVE_SMOKE_BROKER_FILLED"
UPBIT_LIVE_SMOKE_CANCEL_REQUESTED = "UPBIT_LIVE_SMOKE_CANCEL_REQUESTED"
UPBIT_LIVE_SMOKE_CANCEL_SENT = "UPBIT_LIVE_SMOKE_CANCEL_SENT"
UPBIT_LIVE_SMOKE_CANCEL_CONFIRMED = "UPBIT_LIVE_SMOKE_CANCEL_CONFIRMED"
UPBIT_LIVE_SMOKE_CANCEL_FAILED = "UPBIT_LIVE_SMOKE_CANCEL_FAILED"
UPBIT_LIVE_SMOKE_STATUS_UNKNOWN = "UPBIT_LIVE_SMOKE_STATUS_UNKNOWN"
UPBIT_LIVE_SMOKE_MANUAL_REVIEW_REQUIRED = (
    "UPBIT_LIVE_SMOKE_MANUAL_REVIEW_REQUIRED"
)


def mask_broker_uuid(value: str | None) -> str | None:
    """UUID 마스킹 — 앞 8자만."""

    if not value:
        return None
    raw = str(value).strip()
    if len(raw) <= 8:
        return raw[:2] + "***"
    return f"{raw[:8]}…{raw[-4:]}"


def smoke_broker_identifier(run_id: str) -> str:
    return f"live-smoke:{run_id}"
