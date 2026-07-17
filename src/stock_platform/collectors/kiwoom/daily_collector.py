from __future__ import annotations

from datetime import date
from typing import Final

import structlog

from stock_platform.brokers.kiwoom.client import KiwoomRestClient
from stock_platform.collectors.kiwoom.dto import DailyPriceDTO
from stock_platform.collectors.kiwoom.pagination import ContinuationState
from stock_platform.collectors.kiwoom.parser import KiwoomDailyParser


logger = structlog.get_logger(__name__)


class KiwoomDailyCollectionError(RuntimeError):
    """키움 일봉 수집 실패."""


class KiwoomDailyCollector:
    """키움 REST ka10081 일봉 수집기."""

    API_ID: Final[str] = "ka10081"
    ENDPOINT: Final[str] = "/api/dostk/chart"

    def __init__(
        self,
        client: KiwoomRestClient,
        parser: KiwoomDailyParser | None = None,
    ) -> None:
        self._client = client
        self._parser = parser or KiwoomDailyParser()

    async def collect(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        *,
        adjusted_price: bool = True,
        max_pages: int = 100,
    ) -> list[DailyPriceDTO]:
        """
        지정 기간의 국내주식 일봉을 수집한다.

        ka10081은 기준일 이전 데이터를 최신순으로 반환하는 방식이므로,
        end_date를 기준일로 요청하고 start_date 이전 데이터가 나오면
        연속조회를 중단한다.
        """
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("symbol is required")

        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")

        if max_pages <= 0:
            raise ValueError("max_pages must be greater than zero")

        request_body = {
            "stk_cd": normalized_symbol,
            "base_dt": end_date.strftime("%Y%m%d"),
            "upd_stkpc_tp": "1" if adjusted_price else "0",
        }

        continuation = ContinuationState()
        prices_by_date: dict[date, DailyPriceDTO] = {}

        for page_number in range(1, max_pages + 1):
            response = await self._client.request(
                api_id=self.API_ID,
                endpoint=self.ENDPOINT,
                body=request_body,
                continue_yn=continuation.continue_yn,
                next_key=continuation.next_key,
            )

            page_rows = self._parser.parse(response.body)

            logger.info(
                "kiwoom_daily_page_collected",
                symbol=normalized_symbol,
                page=page_number,
                row_count=len(page_rows),
                has_more=response.has_more,
            )

            if not page_rows:
                break

            oldest_date: date | None = None

            for row in page_rows:
                if oldest_date is None or row.trade_date < oldest_date:
                    oldest_date = row.trade_date

                if start_date <= row.trade_date <= end_date:
                    prices_by_date[row.trade_date] = row

            if oldest_date is not None and oldest_date <= start_date:
                break

            continuation = ContinuationState.from_response(
                has_more=response.has_more,
                next_key=response.next_key,
            )
            if not continuation.has_more:
                break
        else:
            raise KiwoomDailyCollectionError(
                f"Exceeded max_pages={max_pages} for {normalized_symbol}"
            )

        result = sorted(
            prices_by_date.values(),
            key=lambda item: item.trade_date,
        )

        logger.info(
            "kiwoom_daily_collection_completed",
            symbol=normalized_symbol,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            row_count=len(result),
        )

        return result
