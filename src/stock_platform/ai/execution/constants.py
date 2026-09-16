"""STEP 11-5 — AI Execution 상수·상태."""

from __future__ import annotations

from enum import StrEnum

# 이번 STEP 실행 허용 (STEP 11-5 ~ 11-10)
EXECUTABLE_TASK_TYPES = frozenset(
    {
        "CHAT",
        "SUMMARIZE",
        "NEWS_ANALYSIS",
        "DISCLOSURE_ANALYSIS",
        "CHART_ANALYSIS",
        "MARKET_ANALYSIS",
        "STOCK_CANDIDATE_ANALYSIS",
        "CRYPTO_CANDIDATE_ANALYSIS",
        "STOCK_CANDIDATE_CONSENSUS",
        "CRYPTO_CANDIDATE_CONSENSUS",
    }
)

# 정의만 유지 — 실행 금지
BLOCKED_TASK_TYPES = frozenset(
    {
        "STRATEGY_DRAFT",
        "STRATEGY_REVIEW",
        "RISK_REVIEW",
        "PORTFOLIO_REVIEW",
    }
)


class RequestStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    SUCCEEDED_WITH_WARNINGS = "SUCCEEDED_WITH_WARNINGS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    ABANDONED = "ABANDONED"


class RunStatus(StrEnum):
    CREATED = "CREATED"
    STARTED = "STARTED"
    PROVIDER_SUCCEEDED = "PROVIDER_SUCCEEDED"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    VALIDATION_SUCCEEDED = "VALIDATION_SUCCEEDED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    FALLBACK_SCHEDULED = "FALLBACK_SCHEDULED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    COMPLETED = "COMPLETED"


class ExecutionMode(StrEnum):
    DRY_RUN = "DRY_RUN"
    MOCK = "MOCK"
    EXTERNAL = "EXTERNAL"


TERMINAL_REQUEST = frozenset(
    {
        RequestStatus.SUCCEEDED,
        RequestStatus.SUCCEEDED_WITH_WARNINGS,
        RequestStatus.FAILED,
        RequestStatus.BLOCKED,
        RequestStatus.CANCELLED,
        RequestStatus.TIMED_OUT,
        RequestStatus.ABANDONED,
    }
)

# Request 허용 전이
REQUEST_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    RequestStatus.DRAFT: frozenset(
        {RequestStatus.READY, RequestStatus.CANCELLED}
    ),
    RequestStatus.READY: frozenset(
        {
            RequestStatus.QUEUED,
            RequestStatus.RUNNING,
            RequestStatus.CANCELLED,
            RequestStatus.BLOCKED,
            RequestStatus.FAILED,
        }
    ),
    RequestStatus.QUEUED: frozenset(
        {
            RequestStatus.RUNNING,
            RequestStatus.CANCELLED,
            RequestStatus.TIMED_OUT,
            RequestStatus.ABANDONED,
        }
    ),
    RequestStatus.RUNNING: frozenset(
        {
            RequestStatus.SUCCEEDED,
            RequestStatus.SUCCEEDED_WITH_WARNINGS,
            RequestStatus.FAILED,
            RequestStatus.BLOCKED,
            RequestStatus.CANCEL_REQUESTED,
            RequestStatus.CANCELLED,
            RequestStatus.TIMED_OUT,
            RequestStatus.ABANDONED,
        }
    ),
    RequestStatus.CANCEL_REQUESTED: frozenset(
        {
            RequestStatus.CANCELLED,
            RequestStatus.TIMED_OUT,
            RequestStatus.ABANDONED,
            # 늦은 결과는 덮어쓰지 않음 — CANCELLED만
        }
    ),
}

MAX_RETRY_ATTEMPTS = 2
MAX_TOTAL_PROVIDER_CALLS = 4
DEFAULT_LEASE_SECONDS = 120
MAX_INPUT_CHARS = 40_000
MAX_RESULT_CHARS = 50_000
