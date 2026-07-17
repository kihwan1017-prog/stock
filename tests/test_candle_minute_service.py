from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.collectors.upbit.minute_collector import (
    UpbitMinuteParser,
)
from stock_platform.markets.models import ALLOWED_MINUTE_TIMEFRAMES
from stock_platform.markets.service import CandleMinuteService


class FakeCandleRepo:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.instrument = type(
            "I",
            (),
            {"instrument_id": 1},
        )()

    def find_instrument(self, exchange_code: str, symbol: str):
        return self.instrument

    def upsert_many(self, rows):
        self.rows.extend(rows)
        return len(list(rows))

    def list_recent(self, instrument_id, timeframe, *, limit=200):
        return []

    def find_latest(self, instrument_id, timeframe):
        return None


def test_allowed_timeframes() -> None:
    assert ALLOWED_MINUTE_TIMEFRAMES == (1, 3, 5, 15)


def test_minute_parser() -> None:
    rows = UpbitMinuteParser().parse(
        [
            {
                "candle_date_time_utc": "2026-07-18T00:01:00",
                "opening_price": 100,
                "high_price": 110,
                "low_price": 90,
                "trade_price": 105,
                "candle_acc_trade_volume": 1.5,
                "candle_acc_trade_price": 150,
            }
        ]
    )
    assert len(rows) == 1
    assert rows[0].close_price == Decimal("105")
    assert rows[0].candle_at.tzinfo is not None


def test_candle_minute_service_rejects_bad_ohlc() -> None:
    service = CandleMinuteService(
        FakeCandleRepo(),  # type: ignore[arg-type]
    )

    try:
        service.save_many(
            exchange_code="UPBIT",
            symbol="KRW-BTC",
            timeframe=1,
            source="UPBIT",
            rows=[
                {
                    "candle_at": datetime(
                        2026, 7, 18, tzinfo=timezone.utc
                    ),
                    "open_price": 1,
                    "high_price": 1,
                    "low_price": 2,
                    "close_price": 1,
                }
            ],
        )
        raised = False
    except ValueError:
        raised = True

    assert raised is True


def test_candle_minute_service_upserts() -> None:
    repo = FakeCandleRepo()
    service = CandleMinuteService(repo)  # type: ignore[arg-type]

    saved = service.save_many(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        timeframe=5,
        source="UPBIT",
        rows=[
            {
                "candle_at": datetime(
                    2026, 7, 18, 1, 0, tzinfo=timezone.utc
                ),
                "open_price": 1,
                "high_price": 2,
                "low_price": 1,
                "close_price": 1.5,
                "volume": 10,
            }
        ],
    )

    assert saved == 1
    assert repo.rows[0]["timeframe"] == 5
