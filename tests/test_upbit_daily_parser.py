from datetime import date
from decimal import Decimal

from stock_platform.collectors.upbit.parser import (
    UpbitDailyParser,
)


def test_parse_day_candle() -> None:
    parser = UpbitDailyParser()

    rows = [
        {
            "market": "KRW-BTC",
            "candle_date_time_utc": "2026-07-12T00:00:00",
            "candle_date_time_kst": "2026-07-12T09:00:00",
            "opening_price": 100000000,
            "high_price": 102000000,
            "low_price": 99000000,
            "trade_price": 101000000,
            "candle_acc_trade_price": 1234567890.5,
            "candle_acc_trade_volume": 12.345,
            "signed_change_rate": 0.01,
        }
    ]

    result = parser.parse(rows)

    assert result[0].trade_date == date(2026, 7, 12)
    assert result[0].close_price == Decimal("101000000")
    assert result[0].volume == Decimal("12.345")
    assert result[0].change_rate == Decimal("1.00")
