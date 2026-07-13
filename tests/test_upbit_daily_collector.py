from datetime import date

import pytest

from stock_platform.collectors.upbit.daily_collector import (
    UpbitDailyCollector,
)


class FakeUpbitClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def list_day_candles(self, **kwargs):
        self.calls.append(kwargs)

        if len(self.calls) == 1:
            return [
                {
                    "candle_date_time_utc": "2026-07-10T00:00:00",
                    "candle_date_time_kst": "2026-07-10T09:00:00",
                    "opening_price": 10,
                    "high_price": 12,
                    "low_price": 9,
                    "trade_price": 11,
                    "candle_acc_trade_price": 1000,
                    "candle_acc_trade_volume": 100,
                    "signed_change_rate": 0.1,
                },
                {
                    "candle_date_time_utc": "2026-07-09T00:00:00",
                    "candle_date_time_kst": "2026-07-09T09:00:00",
                    "opening_price": 9,
                    "high_price": 10,
                    "low_price": 8,
                    "trade_price": 9,
                    "candle_acc_trade_price": 900,
                    "candle_acc_trade_volume": 90,
                    "signed_change_rate": 0.0,
                },
            ]

        return [
            {
                "candle_date_time_utc": "2026-07-08T00:00:00",
                "candle_date_time_kst": "2026-07-08T09:00:00",
                "opening_price": 8,
                "high_price": 9,
                "low_price": 7,
                "trade_price": 8,
                "candle_acc_trade_price": 800,
                "candle_acc_trade_volume": 80,
                "signed_change_rate": -0.1,
            }
        ]


@pytest.mark.asyncio
async def test_collect_paginates_and_sorts() -> None:
    client = FakeUpbitClient()
    collector = UpbitDailyCollector(client)  # type: ignore[arg-type]

    result = await collector.collect(
        market="KRW-BTC",
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )

    assert [item.trade_date for item in result] == [
        date(2026, 7, 8),
        date(2026, 7, 9),
        date(2026, 7, 10),
    ]
    assert len(client.calls) == 2
    assert client.calls[0]["market"] == "KRW-BTC"
    assert client.calls[0]["count"] == 200
