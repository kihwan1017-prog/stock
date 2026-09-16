"""COV-C: observation-window source range reconciliation (no N+1).

path_quality / evaluator에 evidence를 전달한다.
COMPLETED gate는 변경하지 않는다. synthetic candle 금지.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import structlog
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
    as_utc,
    floor_minute,
)
from stock_platform.operation.upbit_opportunity_shadow.path_quality import (
    expected_minute_slots,
)

logger = structlog.get_logger(__name__)

# minute 상태 (문서용 — path_quality count로 집계)
STATE_DB_PRESENT = "DB_PRESENT"
STATE_DB_MISSING_SOURCE_PRESENT = "DB_MISSING_SOURCE_PRESENT"
STATE_SOURCE_ABSENT_CONFIRMED = "SOURCE_ABSENT_CONFIRMED"
STATE_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
STATE_SOURCE_NOT_CHECKED = "SOURCE_NOT_CHECKED"


@dataclass(slots=True)
class SourceRangeEvidence:
    """path_quality / evaluation_detail provenance용 PURE 스냅샷."""

    source_check_performed: bool = False
    source_check_started_at: str | None = None
    source_check_completed_at: str | None = None
    source_check_result: str = "NOT_CHECKED"
    # OK | SKIPPED_NO_MISSING | SKIPPED_NO_SYNC | UNAVAILABLE | ERROR
    source_candle_count: int = 0
    source_absent_confirmed_ats: set[datetime] = field(default_factory=set)
    db_missing_source_present_ats: set[datetime] = field(default_factory=set)
    source_unavailable: bool = False
    requests: int = 0
    error_code: str | None = None
    upserted_count: int = 0
    rate_limited: bool = False

    def absent_ats(self) -> set[datetime]:
        return set(self.source_absent_confirmed_ats)

    def to_detail_dict(self) -> dict[str, Any]:
        return {
            "source_check_performed": self.source_check_performed,
            "source_check_started_at": self.source_check_started_at,
            "source_check_completed_at": self.source_check_completed_at,
            "source_check_result": self.source_check_result,
            "source_candle_count": self.source_candle_count,
            "source_absent_confirmed": len(self.source_absent_confirmed_ats),
            "db_missing_source_present": len(self.db_missing_source_present_ats),
            "source_unavailable": self.source_unavailable,
            "requests": self.requests,
            "error_code": self.error_code,
            "upserted_count": self.upserted_count,
            "rate_limited": self.rate_limited,
        }


def classify_expected_minutes(
    *,
    expected: Sequence[datetime],
    db_ats: set[datetime],
    source_ats: set[datetime] | None,
    check_performed: bool,
    source_unavailable: bool,
) -> dict[str, set[datetime]]:
    """expected minute → 상태 집합. synthetic 생성 없음."""

    db_present: set[datetime] = set()
    missing_present: set[datetime] = set()
    absent: set[datetime] = set()
    unavailable: set[datetime] = set()
    not_checked: set[datetime] = set()

    for t in expected:
        at = floor_minute(as_utc(t))
        if at in db_ats:
            db_present.add(at)
            continue
        if source_unavailable or (check_performed and source_ats is None):
            unavailable.add(at)
            continue
        if not check_performed or source_ats is None:
            not_checked.add(at)
            continue
        if at in source_ats:
            missing_present.add(at)
        else:
            absent.add(at)

    return {
        STATE_DB_PRESENT: db_present,
        STATE_DB_MISSING_SOURCE_PRESENT: missing_present,
        STATE_SOURCE_ABSENT_CONFIRMED: absent,
        STATE_SOURCE_UNAVAILABLE: unavailable,
        STATE_SOURCE_NOT_CHECKED: not_checked,
    }


async def fetch_source_minute_ats(
    *,
    symbol: str,
    start_at: datetime,
    end_at: datetime,
    timeframe: int = 1,
) -> tuple[set[datetime] | None, dict[str, Any]]:
    """1회 range collect → candle_at set. 실패 시 (None, meta)."""

    meta: dict[str, Any] = {
        "requests": 0,
        "error_code": None,
        "rate_limited": False,
        "collected_count": 0,
    }
    try:
        from stock_platform.broker.upbit.market.client import (
            UpbitQuotationClient,
        )
        from stock_platform.broker.upbit.exceptions import (
            UpbitRateLimitError,
        )
        from stock_platform.collectors.upbit.minute_collector import (
            UpbitMinuteCollector,
        )

        start = floor_minute(as_utc(start_at))
        end = as_utc(end_at)
        async with UpbitQuotationClient() as client:
            collector = UpbitMinuteCollector(client)
            meta["requests"] = 1
            collected = await collector.collect(
                market=symbol.upper(),
                timeframe=int(timeframe),
                start_at=start,
                end_at=end,
            )
        # pagination may issue multiple GETs inside collect — count pages approx
        # collector loops pages; we cannot see exact without hook — use ceil
        span_min = max(1, int((end - start).total_seconds() // 60) + 1)
        meta["requests"] = max(1, (span_min + 199) // 200)
        meta["collected_count"] = len(collected)
        ats = {floor_minute(as_utc(item.candle_at)) for item in collected}
        return ats, meta
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        meta["error_code"] = name
        try:
            from stock_platform.broker.upbit.exceptions import (
                UpbitRateLimitError,
            )

            if isinstance(exc, UpbitRateLimitError):
                meta["rate_limited"] = True
        except Exception:  # noqa: BLE001
            if "RateLimit" in name or "429" in name:
                meta["rate_limited"] = True
        logger.warning(
            "shadow_source_range_fetch_failed",
            symbol=symbol,
            error=name,
        )
        return None, meta


async def upsert_source_present_minutes(
    session: Session,
    *,
    symbol: str,
    start_at: datetime,
    end_at: datetime,
    timeframe: int = 1,
) -> dict[str, Any]:
    """기존 UpbitMinuteSyncService(resume=False)로 DB 보충."""

    from stock_platform.broker.upbit.market.client import UpbitQuotationClient
    from stock_platform.collectors.upbit.minute_collector import (
        UpbitMinuteCollector,
    )
    from stock_platform.collectors.upbit.minute_sync_service import (
        UpbitMinuteSyncService,
    )
    from stock_platform.markets.repository import (
        CandleMinuteRepository,
        InstrumentRepository,
    )
    from stock_platform.markets.service import (
        CandleMinuteService,
        InstrumentService,
    )

    start = floor_minute(as_utc(start_at))
    end = as_utc(end_at)
    async with UpbitQuotationClient() as client:
        instr = InstrumentService(InstrumentRepository(session))
        candle = CandleMinuteService(
            CandleMinuteRepository(session),
            instrument_service=instr,
        )
        result = await UpbitMinuteSyncService(
            collector=UpbitMinuteCollector(client),
            candle_service=candle,
            instrument_service=instr,
        ).sync(
            market=symbol.upper(),
            timeframe=int(timeframe),
            start_at=start,
            end_at=end,
            resume=False,
        )
    return {
        "ok": True,
        "collected_count": int(getattr(result, "collected_count", 0) or 0),
        "saved_count": int(getattr(result, "saved_count", 0) or 0),
    }


async def reconcile_observation_source(
    session: Session,
    *,
    symbol: str,
    detected_at: datetime,
    terminal_at: datetime,
    now: datetime,
    bars: Sequence[MinuteBar],
    timeframe: int = 1,
    allow_sync: bool = True,
    persist_upsert: bool = True,
) -> tuple[list[MinuteBar], SourceRangeEvidence]:
    """observation window [detected, terminal] source reconcile.

    persist_upsert=False → fetch+classify only (dry / historical safety).
    """

    from stock_platform.operation.upbit_opportunity_shadow.candle_loader import (
        list_minute_bars_db,
    )

    evidence = SourceRangeEvidence()
    detected = as_utc(detected_at)
    terminal = as_utc(terminal_at)
    now_utc = as_utc(now)
    eval_end = min(now_utc, terminal)

    expected = expected_minute_slots(
        detected_at=detected, end_at=terminal, now=now_utc
    )
    db_ats = {
        floor_minute(as_utc(b.candle_at))
        for b in bars
        if floor_minute(as_utc(b.candle_at))
        in {floor_minute(as_utc(t)) for t in expected}
    }
    # also accept all bars in range
    db_ats = {
        floor_minute(as_utc(b.candle_at))
        for b in bars
    }
    expected_set = set(expected)
    db_ats = {t for t in db_ats if t in expected_set}
    missing = [t for t in expected if t not in db_ats]

    out_bars = list(bars)
    if not missing:
        evidence.source_check_result = "SKIPPED_NO_MISSING"
        evidence.source_check_performed = False
        return out_bars, evidence

    if not allow_sync:
        evidence.source_check_result = "SKIPPED_NO_SYNC"
        evidence.source_check_performed = False
        return out_bars, evidence

    started = datetime.now(timezone.utc)
    evidence.source_check_started_at = started.isoformat()
    evidence.source_check_performed = True

    source_ats, meta = await fetch_source_minute_ats(
        symbol=symbol,
        start_at=floor_minute(detected),
        end_at=eval_end,
        timeframe=timeframe,
    )
    evidence.requests = int(meta.get("requests") or 0)
    evidence.error_code = meta.get("error_code")
    evidence.rate_limited = bool(meta.get("rate_limited"))

    if source_ats is None:
        evidence.source_unavailable = True
        evidence.source_check_result = (
            "UNAVAILABLE_RATE_LIMITED"
            if evidence.rate_limited
            else "UNAVAILABLE"
        )
        evidence.source_check_completed_at = datetime.now(
            timezone.utc
        ).isoformat()
        return out_bars, evidence

    evidence.source_candle_count = len(source_ats)
    classified = classify_expected_minutes(
        expected=expected,
        db_ats=db_ats,
        source_ats=source_ats,
        check_performed=True,
        source_unavailable=False,
    )
    evidence.source_absent_confirmed_ats = set(
        classified[STATE_SOURCE_ABSENT_CONFIRMED]
    )
    evidence.db_missing_source_present_ats = set(
        classified[STATE_DB_MISSING_SOURCE_PRESENT]
    )
    evidence.source_check_result = "OK"

    # DB에 source present 분 보충 (realtime soft-sync 재사용)
    if (
        persist_upsert
        and evidence.db_missing_source_present_ats
        and allow_sync
    ):
        try:
            up = await upsert_source_present_minutes(
                session,
                symbol=symbol,
                start_at=floor_minute(detected),
                end_at=eval_end,
                timeframe=timeframe,
            )
            evidence.upserted_count = int(up.get("saved_count") or 0)
            evidence.requests += 1
            # reload DB bars for window
            out_bars = list_minute_bars_db(
                session,
                symbol=symbol,
                start_at=floor_minute(detected) - timedelta(minutes=1),
                end_at=eval_end,
                timeframe=timeframe,
            )
            # reclassify absent after upsert (present should shrink)
            db_ats2 = {
                floor_minute(as_utc(b.candle_at))
                for b in out_bars
                if floor_minute(as_utc(b.candle_at)) in expected_set
            }
            classified2 = classify_expected_minutes(
                expected=expected,
                db_ats=db_ats2,
                source_ats=source_ats,
                check_performed=True,
                source_unavailable=False,
            )
            evidence.source_absent_confirmed_ats = set(
                classified2[STATE_SOURCE_ABSENT_CONFIRMED]
            )
            evidence.db_missing_source_present_ats = set(
                classified2[STATE_DB_MISSING_SOURCE_PRESENT]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "shadow_source_upsert_failed",
                symbol=symbol,
                error=type(exc).__name__,
            )
            evidence.error_code = type(exc).__name__
            # absence evidence는 fetch 성공분이 유효 — upsert 실패만 기록

    evidence.source_check_completed_at = datetime.now(timezone.utc).isoformat()
    return out_bars, evidence


def dry_reconcile_from_sets(
    *,
    expected: Sequence[datetime],
    db_ats: set[datetime],
    source_ats: set[datetime] | None,
    source_unavailable: bool = False,
    check_performed: bool = True,
) -> dict[str, Any]:
    """unit/dry helper — network 없음."""

    classified = classify_expected_minutes(
        expected=expected,
        db_ats=db_ats,
        source_ats=source_ats,
        check_performed=check_performed,
        source_unavailable=source_unavailable,
    )
    return {k: sorted(v) for k, v in classified.items()}
