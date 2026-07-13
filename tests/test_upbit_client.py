import asyncio

import httpx

from stock_platform.brokers.upbit.client import (
    UpbitQuotationClient,
)
from stock_platform.common.settings import Settings


def _settings() -> Settings:
    return Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        upbit_base_url="https://api.upbit.com",
    )


def test_list_day_candles() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/candles/days"
        assert request.url.params["market"] == "KRW-BTC"
        assert request.url.params["count"] == "200"

        return httpx.Response(
            200,
            json=[
                {
                    "market": "KRW-BTC",
                    "candle_date_time_utc": "2026-07-12T00:00:00",
                    "candle_date_time_kst": "2026-07-12T09:00:00",
                    "opening_price": 1,
                    "high_price": 2,
                    "low_price": 1,
                    "trade_price": 2,
                }
            ],
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            transport=transport,
        ) as http_client:
            client = UpbitQuotationClient(
                settings=_settings(),
                http_client=http_client,
            )

            result = await client.list_day_candles(
                market="KRW-BTC",
                count=200,
            )

            assert len(result) == 1

    asyncio.run(run())
