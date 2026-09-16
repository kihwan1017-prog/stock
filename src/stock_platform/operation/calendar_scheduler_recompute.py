"""STEP 8-5-11/8-5-13/8-5-15 — Calendar 변경 후 Session Job 재계산.

STEP 8-5-15부터 Job은 `operation.market_session_job` 테이블에 영속화되며
DB가 Source of Truth다. `calendar_change_service.apply()`가 자신의
SQLAlchemy Session을 넘기면 Calendar 변경과 Job 생성이 하나의 트랜잭션으로
묶인다 (커밋은 항상 호출자 책임).

`_DYNAMIC_JOBS`(프로세스 메모리)는 더 이상 Source of Truth가 아니며,
테스트/디버깅 참고용 Deprecated 미러로만 남긴다. Admin API 등 실제 조회는
반드시 DB(`MarketSessionJobService`)를 거쳐야 한다.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from stock_platform.operation.calendar_constants import KRX_TIMEZONE

logger = logging.getLogger(__name__)

# Deprecated — 관측/테스트 참고용 메모리 미러. DB가 Source of Truth.
_DYNAMIC_JOBS: dict[str, dict[str, Any]] = {}


def build_job_id(
    *,
    exchange_code: str,
    market_date: date,
    job_type: str,
    revision: int,
) -> str:
    """레거시 Job Key 포맷 — `market_session_job_constants.build_job_key`와 동일."""

    return (
        f"{exchange_code.upper()}:{market_date.isoformat()}"
        f":{job_type}:rev{int(revision)}"
    )


def _parse_hhmmss(value: Any, default: time) -> time:
    if value is None:
        return default
    if isinstance(value, time):
        return value
    raw = str(value).strip()
    parts = raw.split(":")
    if len(parts) < 2:
        return default
    h, m = int(parts[0]), int(parts[1])
    s = int(parts[2]) if len(parts) > 2 else 0
    return time(h, m, s)


def recompute_krx_session_jobs(
    *,
    exchange_code: str,
    market_date: date,
    revision: int,
    session_snapshot: dict[str, Any],
    session: Session | None = None,
) -> dict[str, Any]:
    """오늘/미래 날짜만 Job 재등록. 과거는 no-op.

    STEP 8-5-13 — 고정 오프셋 대신 TradingSessionTimelineResolver가
    계산한 시각(지연개장/조기종료 반영)을 사용한다.

    STEP 8-5-15 — ``session``이 주어지면 호출자(Calendar 변경 트랜잭션)와
    동일 세션으로 DB에 Job을 영속화한다(commit은 호출자 책임). 주어지지
    않으면 새 세션을 열어 즉시 commit한다(Admin 강제 재계산 등 단독 호출).
    """

    exchange = exchange_code.upper()
    tz = ZoneInfo(KRX_TIMEZONE)
    today = datetime.now(tz).date()
    if market_date < today:
        return {
            "status": "SKIPPED_PAST",
            "removed": 0,
            "registered": 0,
        }

    # 이번 Revision을 계산하기 전에 Timeline Cache를 비워
    # 최신 Calendar 상태로 다시 계산되도록 한다.
    try:
        from stock_platform.operation.session_timeline import (
            invalidate_timeline_cache,
        )

        invalidate_timeline_cache(
            exchange_code=exchange, market_date=market_date
        )
    except Exception:  # noqa: BLE001
        pass

    is_trading = bool(session_snapshot.get("is_trading_day", True))
    session_type = str(session_snapshot.get("session_type") or "")

    owns_session = session is None
    if session is None:
        from stock_platform.database.session import get_session_factory

        session = get_session_factory()()

    from stock_platform.operation.market_session_job_service import (
        MarketSessionJobService,
    )

    try:
        job_svc = MarketSessionJobService(session)

        if not is_trading or session_type == "CLOSED":
            superseded = job_svc.supersede_previous_revision(
                exchange_code=exchange,
                market_date=market_date,
                new_revision=revision,
            )
            if owns_session:
                session.commit()
            logger.info(
                "calendar_scheduler_recompute_closed",
                extra={
                    "exchange": exchange,
                    "date": market_date.isoformat(),
                    "revision": revision,
                    "superseded": superseded,
                },
            )
            return {
                "status": "OK_CLOSED",
                "removed": superseded,
                "registered": 0,
                "job_ids": [],
            }

        open_t = _parse_hhmmss(
            session_snapshot.get("regular_open_at"), time(9, 0)
        )
        close_t = _parse_hhmmss(
            session_snapshot.get("regular_close_at"), time(15, 30)
        )
        preopen_raw = session_snapshot.get("preopen_at")
        preopen_t = (
            _parse_hhmmss(preopen_raw, time(8, 30))
            if preopen_raw
            else None
        )

        from stock_platform.operation.session_timeline import (
            TradingSessionTimelineResolver,
        )

        timeline = TradingSessionTimelineResolver().resolve_from_decision(
            exchange_code=exchange,
            market_date=market_date,
            is_trading_day=True,
            live_allowed=True,
            reason_code=str(
                session_snapshot.get("reason_code") or "CALENDAR_OPEN"
            ),
            session_type=session_type or None,
            regular_open_at=open_t,
            regular_close_at=close_t,
            preopen_at=preopen_t,
            revision=revision,
            timezone=str(session_snapshot.get("timezone") or KRX_TIMEZONE),
        )

        result = job_svc.create_or_supersede_for_revision(
            exchange_code=exchange,
            market_date=market_date,
            revision=revision,
            timeline=timeline,
        )
        if owns_session:
            session.commit()
    except Exception:
        if owns_session:
            session.rollback()
        raise
    finally:
        if owns_session:
            session.close()

    created = result.get("created") or []
    _mirror_to_memory(
        exchange_code=exchange,
        market_date=market_date,
        revision=revision,
        timeline=timeline,
        created=created,
    )

    logger.info(
        "calendar_scheduler_recompute_ok",
        extra={
            "exchange": exchange,
            "date": market_date.isoformat(),
            "revision": revision,
            "registered": len(created),
            "superseded": result.get("superseded", 0),
        },
    )
    return {
        "status": "OK",
        "removed": result.get("superseded", 0),
        "registered": len(created),
        "job_ids": [c["job_id"] for c in created],
    }


def _mirror_to_memory(
    *,
    exchange_code: str,
    market_date: date,
    revision: int,
    timeline: Any,
    created: list[dict[str, Any]],
) -> None:
    """Deprecated 메모리 미러 — 테스트/디버깅 참고용, Source of Truth 아님."""

    plan = {
        c["job_type"]: getattr(
            timeline,
            {
                "KRX_PREOPEN_RECOVERY": "recovery_preopen_at",
                "KRX_POSTCLOSE_RECOVERY": "recovery_postclose_at",
                "KRX_EQUITY_SNAPSHOT": "snapshot_at",
                "KRX_SETTLEMENT": "settlement_at",
                "KRX_AI_ANALYSIS": "analysis_at",
            }.get(c["job_type"], ""),
            None,
        )
        for c in created
    }
    for job_type, run_at in plan.items():
        job_id = build_job_id(
            exchange_code=exchange_code,
            market_date=market_date,
            job_type=job_type,
            revision=revision,
        )
        _DYNAMIC_JOBS[job_id] = {
            "status": "SCHEDULED",
            "run_at": run_at.isoformat() if run_at else None,
            "revision": revision,
            "job_type": job_type,
            "exchange_code": exchange_code,
            "market_date": market_date.isoformat(),
        }


def list_dynamic_jobs() -> list[dict[str, Any]]:
    """Deprecated — DB(`MarketSessionJobService.list_for_date`)를 대신 사용할 것."""

    return [
        {"job_id": jid, **meta} for jid, meta in _DYNAMIC_JOBS.items()
    ]


def scheduler_recompute_failure_count() -> int:
    return sum(
        1
        for meta in _DYNAMIC_JOBS.values()
        if meta.get("status") == "REGISTER_FAILED"
    )
