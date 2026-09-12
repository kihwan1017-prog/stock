from datetime import date
from decimal import Decimal
from pathlib import Path

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
    assert client.calls[0]["to"] == "2026-07-10T23:59:59+09:00"
    assert client.calls[1]["to"] == "2026-07-09T00:00:00Z"


class DuplicateDateClient:
    async def list_day_candles(self, **kwargs):
        shared = {
            "opening_price": 10,
            "high_price": 12,
            "low_price": 9,
            "trade_price": 11,
            "candle_acc_trade_price": 1000,
            "candle_acc_trade_volume": 100,
        }
        return [
            {
                **shared,
                "candle_date_time_utc": "2026-07-10T00:00:00",
                "candle_date_time_kst": "2026-07-10T09:00:00",
                "trade_price": 11,
            },
            {
                **shared,
                "candle_date_time_utc": "2026-07-10T00:00:00",
                "candle_date_time_kst": "2026-07-10T09:00:00",
                "trade_price": 12,
            },
        ]


@pytest.mark.asyncio
async def test_collect_dedupes_by_trade_date() -> None:
    collector = UpbitDailyCollector(DuplicateDateClient())  # type: ignore[arg-type]
    result = await collector.collect(
        market="KRW-GRVT",
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 10),
    )
    assert len(result) == 1
    assert result[0].close_price == Decimal("12")


class TodayCandleClient:
    async def list_day_candles(self, **kwargs):
        return [
            {
                "candle_date_time_utc": "2026-08-20T00:00:00",
                "candle_date_time_kst": "2026-08-20T09:00:00",
                "opening_price": 10,
                "high_price": 12,
                "low_price": 9,
                "trade_price": 11,
                "candle_acc_trade_price": 1000,
                "candle_acc_trade_volume": 100,
            },
            {
                "candle_date_time_utc": "2026-08-19T00:00:00",
                "candle_date_time_kst": "2026-08-19T09:00:00",
                "opening_price": 9,
                "high_price": 10,
                "low_price": 8,
                "trade_price": 9,
                "candle_acc_trade_price": 900,
                "candle_acc_trade_volume": 90,
            },
        ]


@pytest.mark.asyncio
async def test_collect_skips_incomplete_current_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "stock_platform.collectors.upbit.daily_collector.today_kst",
        lambda: date(2026, 8, 20),
    )
    collector = UpbitDailyCollector(TodayCandleClient())  # type: ignore[arg-type]
    result = await collector.collect(
        market="KRW-GRVT",
        start_date=date(2026, 8, 19),
        end_date=date(2026, 8, 20),
    )
    assert [item.trade_date for item in result] == [date(2026, 8, 19)]


class IsolationClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def list_day_candles(self, **kwargs):
        self.calls.append(kwargs)
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
            }
        ]


@pytest.mark.asyncio
async def test_collect_requests_requested_symbol_only() -> None:
    client = IsolationClient()
    collector = UpbitDailyCollector(client)  # type: ignore[arg-type]
    await collector.collect(
        market="krw-grvt",
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 10),
    )
    assert client.calls[0]["market"] == "KRW-GRVT"
    assert all(call["market"] == "KRW-GRVT" for call in client.calls)


def test_daily_modules_do_not_touch_orders() -> None:
    from pathlib import Path

    roots = [
        Path("src/stock_platform/collectors/upbit/daily_collector.py"),
        Path("src/stock_platform/collectors/upbit/sync_service.py"),
        Path("src/stock_platform/collectors/upbit/parser.py"),
    ]
    forbidden = (
        "TradingOrder",
        "create_order",
        "cancel_order",
        "amend_order",
        "Outbox",
        "BrokerOrder",
    )
    for path in roots:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path} contains {token}"


def test_price_daily_mapping_keys() -> None:
    from datetime import date
    from decimal import Decimal

    from stock_platform.collectors.upbit.dto import UpbitDailyPriceDTO

    row = UpbitDailyPriceDTO(
        trade_date=date(2026, 8, 19),
        open_price=Decimal("1"),
        high_price=Decimal("2"),
        low_price=Decimal("0.5"),
        close_price=Decimal("1.5"),
        volume=Decimal("10"),
        trade_value=Decimal("20"),
        change_rate=None,
    ).to_price_row()
    assert set(row) >= {
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "trade_value",
    }
