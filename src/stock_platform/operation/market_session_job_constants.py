"""STEP 8-5-15 — 영속 Market Session Job 상수.

`_DYNAMIC_JOBS`(프로세스 메모리)를 DB로 대체하기 위한 Job Type/Status/Result
상수. Key 포맷은 기존 `calendar_scheduler_recompute.build_job_id`와 동일하게
유지한다 (`{EX}:{date}:{TYPE}:rev{N}`), Type 이름만 신규로 바뀐다.
"""

from __future__ import annotations

from datetime import date as date_cls
from enum import StrEnum


class MarketSessionJobType(StrEnum):
    """KRX 세션과 연동되는 영속 Job 종류.

    KRX_OPEN_PHASE / NEW_ENTRY_CUTOFF / MARKET_CLOSE / REALTIME_RESYNC는
    별도 DB Job으로 만들지 않는다 — Realtime Phase 전환은 계속 Timeline
    Polling(session_scheduler의 5분 주기 동기화)에 위임한다.
    """

    KRX_PREOPEN_RECOVERY = "KRX_PREOPEN_RECOVERY"
    KRX_POSTCLOSE_RECOVERY = "KRX_POSTCLOSE_RECOVERY"
    KRX_EQUITY_SNAPSHOT = "KRX_EQUITY_SNAPSHOT"
    KRX_SETTLEMENT = "KRX_SETTLEMENT"
    KRX_AI_ANALYSIS = "KRX_AI_ANALYSIS"


class MarketSessionJobStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRY_PENDING = "RETRY_PENDING"
    SKIPPED = "SKIPPED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class MarketSessionJobResult(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    SKIPPED = "SKIPPED"
    RETRY = "RETRY"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    SKIPPED_TOO_LATE = "SKIPPED_TOO_LATE"
    SKIPPED_EXPIRED = "SKIPPED_EXPIRED"
    SKIPPED_ALREADY_EXISTS = "SKIPPED_ALREADY_EXISTS"
    SKIPPED_DEPENDENCY = "SKIPPED_DEPENDENCY"
    SETTLEMENT_NOOP = "SETTLEMENT_NOOP"
    DEFERRED_TO_CRON = "DEFERRED_TO_CRON"


# Claim 가능(=아직 실행되지 않은) 상태
CLAIMABLE_JOB_STATUSES = (
    MarketSessionJobStatus.SCHEDULED.value,
    MarketSessionJobStatus.RETRY_PENDING.value,
)

# 아직 진행 중이거나 대기 중인 상태 (Health/Supersede 판정에 사용)
ACTIVE_JOB_STATUSES = frozenset(
    {
        MarketSessionJobStatus.SCHEDULED.value,
        MarketSessionJobStatus.CLAIMED.value,
        MarketSessionJobStatus.RUNNING.value,
        MarketSessionJobStatus.RETRY_PENDING.value,
    }
)

TERMINAL_JOB_STATUSES = frozenset(
    {
        MarketSessionJobStatus.SUCCEEDED.value,
        MarketSessionJobStatus.FAILED.value,
        MarketSessionJobStatus.SKIPPED.value,
        MarketSessionJobStatus.SUPERSEDED.value,
        MarketSessionJobStatus.CANCELLED.value,
        MarketSessionJobStatus.EXPIRED.value,
    }
)

# POST_CLOSE 계열 — 당일 안이면 다소 늦어도 Catch-up 생성을 허용한다.
POST_CLOSE_JOB_TYPES = frozenset(
    {
        MarketSessionJobType.KRX_POSTCLOSE_RECOVERY.value,
        MarketSessionJobType.KRX_EQUITY_SNAPSHOT.value,
        MarketSessionJobType.KRX_SETTLEMENT.value,
        MarketSessionJobType.KRX_AI_ANALYSIS.value,
    }
)

# 구 CALENDAR_JOB_TYPES(calendar_change_constants) → 신규 MarketSessionJobType.
# MARKET_OPEN/NEW_ENTRY_CUTOFF/MARKET_CLOSE는 DB Job으로 승격하지 않는다.
LEGACY_JOB_TYPE_MAP: dict[str, str] = {
    "PREOPEN_RECOVERY": MarketSessionJobType.KRX_PREOPEN_RECOVERY.value,
    "POST_CLOSE_RECOVERY": MarketSessionJobType.KRX_POSTCLOSE_RECOVERY.value,
    "SNAPSHOT": MarketSessionJobType.KRX_EQUITY_SNAPSHOT.value,
    "AI_ANALYSIS": MarketSessionJobType.KRX_AI_ANALYSIS.value,
}


def build_job_key(
    *,
    exchange_code: str,
    market_date: date_cls,
    job_type: str,
    revision: int,
) -> str:
    """`{EX}:{date}:{TYPE}:rev{N}` — 기존 build_job_id와 동일 포맷."""

    return (
        f"{exchange_code.upper()}:{market_date.isoformat()}"
        f":{job_type}:rev{int(revision)}"
    )
