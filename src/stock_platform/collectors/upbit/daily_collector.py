from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog

from stock_platform.broker.upbit.market.client import UpbitQuotationClient
from stock_platform.collectors.upbit.dto import UpbitDailyPriceDTO
from stock_platform.collectors.upbit.parser import UpbitDailyParser


logger = structlog.get_logger(__name__)
_KST = ZoneInfo("Asia/Seoul")


def today_kst() -> date:
    return datetime.now(_KST).date()


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

        # 당일 진행 중 봉은 completed historical bar가 아니다.
        completed_end = min(end_date, today_kst() - timedelta(days=1))
        if start_date > completed_end:
            return []

        end_date = completed_end

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
            newest_date: date | None = None
            today = today_kst()

            for item in parsed_rows:
                if item.trade_date >= today:
                    # 진행 중 당일 봉은 Backtest completed bar로 쓰지 않는다.
                    continue
                if (
                    oldest_date is None
                    or item.trade_date < oldest_date
                ):
                    oldest_date = item.trade_date
                if (
                    newest_date is None
                    or item.trade_date > newest_date
                ):
                    newest_date = item.trade_date

                if start_date <= item.trade_date <= end_date:
                    rows_by_date[item.trade_date] = item

            logger.info(
                "upbit_daily_page_bounds",
                market=normalized_market,
                page=page,
                oldest=None if oldest_date is None else oldest_date.isoformat(),
                newest=None if newest_date is None else newest_date.isoformat(),
                kept=len(rows_by_date),
            )

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
