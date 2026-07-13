from __future__ import annotations

from datetime import date

import structlog

from stock_platform.brokers.upbit.client import UpbitQuotationClient
from stock_platform.collectors.upbit.dto import UpbitDailyPriceDTO
from stock_platform.collectors.upbit.parser import UpbitDailyParser


logger = structlog.get_logger(__name__)


class UpbitDailyCollectionError(RuntimeError):
    """Raised when daily candle pagination does not converge."""


class UpbitDailyCollector:
    """Collect daily candles from Upbit quotation API."""

    def __init__(
        self,
        client: UpbitQuotationClient,
        parser: UpbitDailyParser | None = None,
    ) -> None:
        self._client = client
        self._parser = parser or UpbitDailyParser()

    async def collect(
        self,
        *,
        market: str,
        start_date: date,
        end_date: date,
        max_pages: int = 100,
    ) -> list[UpbitDailyPriceDTO]:
        normalized_market = market.strip().upper()

        if not normalized_market:
            raise ValueError("market is required")

        if start_date > end_date:
            raise ValueError(
                "start_date must not be after end_date"
            )

        if max_pages <= 0:
            raise ValueError(
                "max_pages must be greater than zero"
            )

        cursor: str | None = (
            f"{end_date.isoformat()}T23:59:59+09:00"
        )
        rows_by_date: dict[date, UpbitDailyPriceDTO] = {}

        for page in range(1, max_pages + 1):
            raw_rows = await self._client.list_day_candles(
                market=normalized_market,
                to=cursor,
                count=200,
            )

            if not raw_rows:
                break

            parsed_rows = self._parser.parse(raw_rows)

            logger.info(
                "upbit_daily_page_collected",
                market=normalized_market,
                page=page,
                row_count=len(parsed_rows),
            )

            oldest_date: date | None = None

            for item in parsed_rows:
                if (
                    oldest_date is None
                    or item.trade_date < oldest_date
                ):
                    oldest_date = item.trade_date

                if start_date <= item.trade_date <= end_date:
                    rows_by_date[item.trade_date] = item

            if oldest_date is not None and oldest_date <= start_date:
                break

            oldest_raw = raw_rows[-1]
            next_cursor = self._parser.utc_cursor(oldest_raw)

            if next_cursor == cursor:
                raise UpbitDailyCollectionError(
                    "Pagination cursor did not advance"
                )

            cursor = next_cursor
        else:
            raise UpbitDailyCollectionError(
                f"Exceeded max_pages={max_pages} "
                f"for {normalized_market}"
            )

        result = sorted(
            rows_by_date.values(),
            key=lambda item: item.trade_date,
        )

        logger.info(
            "upbit_daily_collection_completed",
            market=normalized_market,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            row_count=len(result),
        )

        return result
