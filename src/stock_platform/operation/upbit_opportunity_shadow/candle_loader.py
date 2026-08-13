"""Shadow용 1m candle 로드 — DB 우선, 부족 시 기존 UpbitMinuteSyncService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.markets.models import CandleMinute, Instrument
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
    as_utc,
    bars_from_rows,
    floor_minute,
)

logger = structlog.get_logger(__name__)


def list_minute_bars_db(
    session: Session,
    *,
    symbol: str,
    start_at: datetime,
    end_at: datetime,
    timeframe: int = 1,
) -> list[MinuteBar]:
    start = floor_minute(as_utc(start_at))
    end = as_utc(end_at)
    stmt = (
        select(CandleMinute)
        .join(Instrument, Instrument.instrument_id == CandleMinute.instrument_id)
        .where(
            Instrument.exchange_code == "UPBIT",
            Instrument.symbol == symbol.upper(),
            CandleMinute.timeframe == int(timeframe),
            CandleMinute.candle_at >= start,
            CandleMinute.candle_at <= end,
        )
        .order_by(CandleMinute.candle_at.asc())
    )
    rows = list(session.scalars(stmt))
    return bars_from_rows(rows)


async def ensure_shadow_minute_bars(
    session: Session,
    *,
    symbol: str,
    start_at: datetime,
    end_at: datetime,
    timeframe: int = 1,
    allow_sync: bool = True,
) -> dict[str, Any]:
    """DB 조회 → 부족 시 UpbitMinuteSyncService로 구간 sync → 재조회."""

    start = floor_minute(as_utc(start_at)) - timedelta(minutes=1)
    end = as_utc(end_at)
    now = datetime.now(timezone.utc)
    if end > now:
        end = now

    bars = list_minute_bars_db(
        session,
        symbol=symbol,
        start_at=start,
        end_at=end,
        timeframe=timeframe,
    )
    expected_min = max(
        1, int((end - start).total_seconds() // 60) - 2
    )
    sync_result: dict[str, Any] | None = None
    if allow_sync and len(bars) < expected_min:
        try:
            from stock_platform.broker.upbit.market.client import (
                UpbitQuotationClient,
            )
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

            async with UpbitQuotationClient() as client:
                instr = InstrumentService(InstrumentRepository(session))
                candle = CandleMinuteService(
                    CandleMinuteRepository(session),
                    instrument_service=instr,
                )
                sync_result = await UpbitMinuteSyncService(
                    collector=UpbitMinuteCollector(client),
                    candle_service=candle,
                ).sync(
                    market=symbol.upper(),
                    timeframe=int(timeframe),
                    start_at=start,
                    end_at=end,
                    resume=False,
                )
            bars = list_minute_bars_db(
                session,
                symbol=symbol,
                start_at=start,
                end_at=end,
                timeframe=timeframe,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "shadow_candle_sync_failed",
                symbol=symbol,
                error=type(exc).__name__,
            )
            sync_result = {"ok": False, "error": type(exc).__name__}

    return {
        "symbol": symbol.upper(),
        "bars": bars,
        "count": len(bars),
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "sync": sync_result,
        "orders_created": 0,
    }


def _merge_bars(
    existing: list[MinuteBar],
    extra: list[MinuteBar],
) -> list[MinuteBar]:
    by_at = {as_utc(b.candle_at): b for b in existing}
    for bar in extra:
        by_at[as_utc(bar.candle_at)] = bar
    return [by_at[k] for k in sorted(by_at)]


async def resolve_missing_target_minutes(
    session: Session,
    *,
    symbol: str,
    bars: list[MinuteBar],
    candle_starts: list[datetime],
    timeframe: int = 1,
    allow_sync: bool = True,
) -> dict[str, Any]:
    """matured exact candle 부재 시 sync/API로 absent vs source_unavailable 구분.

    가짜 OHLC를 만들지 않는다. API에 exact가 있으면 그 실측 bar만 병합한다.
    """

    out_bars = list(bars)
    bar_at = {as_utc(b.candle_at) for b in out_bars}
    absent_by_target: dict[str, bool] = {}
    source_unavailable_by_target: dict[str, bool] = {}
    resolve_detail: dict[str, Any] = {}

    pending = [
        as_utc(start)
        for start in candle_starts
        if as_utc(start) not in bar_at
    ]
    if not pending:
        return {
            "bars": out_bars,
            "absent_by_target": absent_by_target,
            "source_unavailable_by_target": source_unavailable_by_target,
            "resolve_detail": resolve_detail,
            "orders_created": 0,
        }

    if not allow_sync:
        # 원천 재확인 불가 → fallback FINAL 금지 (absent 미확정)
        for start in pending:
            resolve_detail[start.isoformat()] = {
                "status": "UNCONFIRMED_NO_SYNC",
            }
        return {
            "bars": out_bars,
            "absent_by_target": absent_by_target,
            "source_unavailable_by_target": source_unavailable_by_target,
            "resolve_detail": resolve_detail,
            "orders_created": 0,
        }

    for start in pending:
        key = start.isoformat()
        # 1) 좁은 구간 DB sync 재시도
        try:
            narrow = await ensure_shadow_minute_bars(
                session,
                symbol=symbol,
                start_at=start - timedelta(minutes=2),
                end_at=start + timedelta(minutes=1),
                timeframe=timeframe,
                allow_sync=True,
            )
            out_bars = _merge_bars(out_bars, list(narrow.get("bars") or []))
            bar_at = {as_utc(b.candle_at) for b in out_bars}
            if start in bar_at:
                resolve_detail[key] = {
                    "status": "EXACT_AFTER_SYNC",
                    "source": "market.candle_minute",
                }
                continue
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "shadow_target_minute_resync_failed",
                symbol=symbol,
                candle_at=key,
                error=type(exc).__name__,
            )
            source_unavailable_by_target[key] = True
            resolve_detail[key] = {
                "status": "SOURCE_UNAVAILABLE",
                "stage": "resync",
                "error": type(exc).__name__,
            }
            continue

        # 2) Upbit API로 exact minute 존재 여부 확인
        try:
            from stock_platform.broker.upbit.market.client import (
                UpbitQuotationClient,
            )
            from stock_platform.collectors.upbit.minute_collector import (
                UpbitMinuteParser,
            )

            to_cursor = (start + timedelta(minutes=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            async with UpbitQuotationClient() as client:
                raw_rows = await client.list_minute_candles(
                    market=symbol.upper(),
                    unit=int(timeframe),
                    to=to_cursor,
                    count=5,
                )
            parsed = UpbitMinuteParser().parse(raw_rows or [])
            exact_dto = next(
                (p for p in parsed if as_utc(p.candle_at) == start),
                None,
            )
            if exact_dto is not None:
                # 실측 API candle — synthetic 아님
                api_bar = MinuteBar(
                    candle_at=as_utc(exact_dto.candle_at),
                    open=exact_dto.open_price,
                    high=exact_dto.high_price,
                    low=exact_dto.low_price,
                    close=exact_dto.close_price,
                )
                out_bars = _merge_bars(out_bars, [api_bar])
                resolve_detail[key] = {
                    "status": "EXACT_FROM_API",
                    "source": "upbit.candles.minutes",
                }
                continue

            absent_by_target[key] = True
            resolve_detail[key] = {
                "status": "TARGET_CANDLE_ABSENT_CONFIRMED",
                "api_rows": len(parsed),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "shadow_target_minute_api_confirm_failed",
                symbol=symbol,
                candle_at=key,
                error=type(exc).__name__,
            )
            source_unavailable_by_target[key] = True
            resolve_detail[key] = {
                "status": "SOURCE_UNAVAILABLE",
                "stage": "api_confirm",
                "error": type(exc).__name__,
            }

    return {
        "bars": out_bars,
        "absent_by_target": absent_by_target,
        "source_unavailable_by_target": source_unavailable_by_target,
        "resolve_detail": resolve_detail,
        "orders_created": 0,
    }
