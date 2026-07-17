from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog

from stock_platform.collectors.upbit.minute_collector import (
    UpbitMinuteCollector,
)
from stock_platform.markets.service import (
    CandleMinuteService,
    InstrumentService,
)


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class UpbitMinuteSyncResult:
    exchange_code: str
    symbol: str
    timeframe: int
    requested_start_at: datetime
    requested_end_at: datetime
    collected_count: int
    saved_count: int


class UpbitMinuteSyncService:
    """업비트 분봉 수집 후 market.candle_minute에 저장한다."""

    def __init__(
        self,
        collector: UpbitMinuteCollector,
        candle_service: CandleMinuteService,
        instrument_service: InstrumentService | None = None,
    ) -> None:
        self._collector = collector
        self._candle_service = candle_service
        self._instrument_service = instrument_service

    async def sync(
        self,
        *,
        market: str,
        timeframe: int,
        start_at: datetime,
        end_at: datetime,
        resume: bool = True,
    ) -> UpbitMinuteSyncResult:
        normalized = market.strip().upper()
        exchange_code = "UPBIT"

        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone.utc)
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=timezone.utc)

        if self._instrument_service is not None:
            self._instrument_service.ensure(
                exchange_code=exchange_code,
                symbol=normalized,
                name=normalized,
                asset_type="CRYPTO",
            )

        effective_start = start_at
        if resume:
            latest = self._candle_service.get_latest(
                exchange_code,
                normalized,
                timeframe,
            )
            if latest is not None:
                candidate = latest.candle_at + timedelta(
                    minutes=timeframe
                )
                if candidate > effective_start:
                    effective_start = candidate

        if effective_start > end_at:
            return UpbitMinuteSyncResult(
                exchange_code=exchange_code,
                symbol=normalized,
                timeframe=timeframe,
                requested_start_at=effective_start,
                requested_end_at=end_at,
                collected_count=0,
                saved_count=0,
            )

        collected = await self._collector.collect(
            market=normalized,
            timeframe=timeframe,
            start_at=effective_start,
            end_at=end_at,
        )

        saved_count = self._candle_service.save_many(
            exchange_code=exchange_code,
            symbol=normalized,
            timeframe=timeframe,
            source="UPBIT",
            rows=[item.to_price_row() for item in collected],
            ensure_instrument=True,
            instrument_name=normalized,
            asset_type="CRYPTO",
        )

        logger.info(
            "upbit_minute_sync_completed",
            market=normalized,
            timeframe=timeframe,
            collected_count=len(collected),
            saved_count=saved_count,
        )

        return UpbitMinuteSyncResult(
            exchange_code=exchange_code,
            symbol=normalized,
            timeframe=timeframe,
            requested_start_at=effective_start,
            requested_end_at=end_at,
            collected_count=len(collected),
            saved_count=saved_count,
        )
