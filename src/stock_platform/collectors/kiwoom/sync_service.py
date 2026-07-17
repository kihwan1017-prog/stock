from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import structlog

from stock_platform.collectors.kiwoom.daily_collector import (
    KiwoomDailyCollector,
)
from stock_platform.markets.service import (
    InstrumentService,
    PriceDailyService,
)


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class KiwoomDailySyncResult:
    exchange_code: str
    symbol: str
    requested_start_date: date
    requested_end_date: date
    collected_count: int
    saved_count: int


class KiwoomDailySyncService:
    """키움 일봉 수집 결과를 market.price_daily에 저장한다."""

    def __init__(
        self,
        collector: KiwoomDailyCollector,
        price_service: PriceDailyService,
        instrument_service: InstrumentService | None = None,
    ) -> None:
        self._collector = collector
        self._price_service = price_service
        self._instrument_service = instrument_service

    async def sync(
        self,
        *,
        symbol: str,
        start_date: date,
        end_date: date,
        exchange_code: str = "KRX",
        adjusted_price: bool = True,
        resume: bool = True,
    ) -> KiwoomDailySyncResult:
        normalized_symbol = symbol.strip().upper()
        normalized_exchange = exchange_code.strip().upper()

        if not normalized_symbol:
            raise ValueError("symbol is required")

        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")

        if self._instrument_service is not None:
            self._instrument_service.ensure(
                exchange_code=normalized_exchange,
                symbol=normalized_symbol,
                name=normalized_symbol,
                asset_type="STOCK",
                currency_code="KRW",
            )

        effective_start_date = start_date

        if resume:
            latest = self._price_service.get_latest(
                exchange_code=normalized_exchange,
                symbol=normalized_symbol,
            )

            if latest is not None:
                resume_date = latest.trade_date + timedelta(days=1)
                if resume_date > effective_start_date:
                    effective_start_date = resume_date

        if effective_start_date > end_date:
            logger.info(
                "kiwoom_daily_sync_skipped",
                symbol=normalized_symbol,
                reason="already_up_to_date",
                end_date=end_date.isoformat(),
            )

            return KiwoomDailySyncResult(
                exchange_code=normalized_exchange,
                symbol=normalized_symbol,
                requested_start_date=effective_start_date,
                requested_end_date=end_date,
                collected_count=0,
                saved_count=0,
            )

        collected = await self._collector.collect(
            symbol=normalized_symbol,
            start_date=effective_start_date,
            end_date=end_date,
            adjusted_price=adjusted_price,
        )

        rows = [item.to_price_row() for item in collected]

        saved_count = self._price_service.save_many(
            exchange_code=normalized_exchange,
            symbol=normalized_symbol,
            source="KIWOOM",
            rows=rows,
            ensure_instrument=True,
            instrument_name=normalized_symbol,
            asset_type="STOCK",
        )

        logger.info(
            "kiwoom_daily_sync_completed",
            exchange_code=normalized_exchange,
            symbol=normalized_symbol,
            start_date=effective_start_date.isoformat(),
            end_date=end_date.isoformat(),
            collected_count=len(collected),
            saved_count=saved_count,
        )

        return KiwoomDailySyncResult(
            exchange_code=normalized_exchange,
            symbol=normalized_symbol,
            requested_start_date=effective_start_date,
            requested_end_date=end_date,
            collected_count=len(collected),
            saved_count=saved_count,
        )
