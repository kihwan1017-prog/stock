from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import structlog

from stock_platform.collectors.upbit.daily_collector import (
    UpbitDailyCollector,
)
from stock_platform.markets.service import (
    InstrumentService,
    PriceDailyService,
)


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class UpbitDailySyncResult:
    exchange_code: str
    symbol: str
    requested_start_date: date
    requested_end_date: date
    collected_count: int
    saved_count: int


class UpbitDailySyncService:
    """Collect and store Upbit daily candles."""

    def __init__(
        self,
        collector: UpbitDailyCollector,
        price_service: PriceDailyService,
        instrument_service: InstrumentService | None = None,
    ) -> None:
        self._collector = collector
        self._price_service = price_service
        self._instrument_service = instrument_service

    async def sync(
        self,
        *,
        market: str,
        start_date: date,
        end_date: date,
        resume: bool = True,
    ) -> UpbitDailySyncResult:
        normalized_market = market.strip().upper()
        exchange_code = "UPBIT"

        if not normalized_market:
            raise ValueError("market is required")

        if self._instrument_service is not None:
            self._instrument_service.ensure(
                exchange_code=exchange_code,
                symbol=normalized_market,
                name=normalized_market,
                asset_type="CRYPTO",
                currency_code="KRW",
            )

        effective_start_date = start_date

        if resume:
            latest = self._price_service.get_latest(
                exchange_code=exchange_code,
                symbol=normalized_market,
            )

            if latest is not None:
                candidate = latest.trade_date + timedelta(days=1)
                if candidate > effective_start_date:
                    effective_start_date = candidate

        if effective_start_date > end_date:
            return UpbitDailySyncResult(
                exchange_code=exchange_code,
                symbol=normalized_market,
                requested_start_date=effective_start_date,
                requested_end_date=end_date,
                collected_count=0,
                saved_count=0,
            )

        collected = await self._collector.collect(
            market=normalized_market,
            start_date=effective_start_date,
            end_date=end_date,
        )

        saved_count = self._price_service.save_many(
            exchange_code=exchange_code,
            symbol=normalized_market,
            source="UPBIT",
            rows=[
                item.to_price_row()
                for item in collected
            ],
            ensure_instrument=True,
            instrument_name=normalized_market,
            asset_type="CRYPTO",
        )

        logger.info(
            "upbit_daily_sync_completed",
            market=normalized_market,
            start_date=effective_start_date.isoformat(),
            end_date=end_date.isoformat(),
            collected_count=len(collected),
            saved_count=saved_count,
        )

        return UpbitDailySyncResult(
            exchange_code=exchange_code,
            symbol=normalized_market,
            requested_start_date=effective_start_date,
            requested_end_date=end_date,
            collected_count=len(collected),
            saved_count=saved_count,
        )
