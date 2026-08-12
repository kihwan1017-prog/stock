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
