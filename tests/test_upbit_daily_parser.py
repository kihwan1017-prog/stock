from datetime import date
from decimal import Decimal

import pytest

from stock_platform.collectors.upbit.parser import (
    UpbitDailyParseError,
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
    assert result[0].open_price == Decimal("100000000")
    assert result[0].high_price == Decimal("102000000")
    assert result[0].low_price == Decimal("99000000")


def _candle(**overrides: object) -> dict:
    row: dict = {
        "market": "KRW-GRVT",
        "candle_date_time_utc": "2026-08-19T00:00:00",
        "candle_date_time_kst": "2026-08-19T09:00:00",
        "opening_price": 100,
        "high_price": 120,
        "low_price": 90,
        "trade_price": 110,
        "candle_acc_trade_price": 1000,
        "candle_acc_trade_volume": 10,
    }
    row.update(overrides)
    return row


def test_kst_trade_date_uses_first_10_chars_of_kst_field() -> None:
    parser = UpbitDailyParser()
    result = parser.parse(
        [
            _candle(
                candle_date_time_utc="2026-08-18T15:00:00",
                candle_date_time_kst="2026-08-19T00:00:00",
            )
        ]
    )
    assert result[0].trade_date == date(2026, 8, 19)


@pytest.mark.parametrize(
    "overrides",
    [
        {"opening_price": 0},
        {"high_price": 0},
        {"low_price": 0},
        {"trade_price": 0},
        {"high_price": 105, "opening_price": 100, "trade_price": 110},
        {"low_price": 105, "opening_price": 100, "trade_price": 110},
        {"candle_acc_trade_volume": -1},
    ],
)
def test_parse_rejects_invalid_ohlc(overrides: dict) -> None:
    parser = UpbitDailyParser()
    with pytest.raises(UpbitDailyParseError):
        parser.parse([_candle(**overrides)])
