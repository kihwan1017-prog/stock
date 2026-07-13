from datetime import date
from types import SimpleNamespace

import pytest

from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)


class FakePriceRepository:
    def __init__(self, instrument=None, prices=None):
        self.instrument = instrument
        self.prices = prices or []

    def find_instrument(self, exchange_code: str, symbol: str):
        return self.instrument

    def find_latest(self, instrument_id: int):
        return self.prices[-1] if self.prices else None

    def find_between(
        self,
        instrument_id: int,
        start_date: date,
        end_date: date,
    ):
        return self.prices

    def upsert_many(self, rows):
        return len(list(rows))


def test_get_between_returns_prices():
    instrument = SimpleNamespace(instrument_id=1)
    prices = [SimpleNamespace(trade_date=date(2026, 7, 10))]
    service = PriceDailyService(
        FakePriceRepository(instrument=instrument, prices=prices)
    )

    result = service.get_between(
        exchange_code="KRX",
        symbol="005930",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 10),
    )

    assert result == prices


def test_get_between_rejects_invalid_date_range():
    service = PriceDailyService(FakePriceRepository())

    with pytest.raises(ValueError):
        service.get_between(
            exchange_code="KRX",
            symbol="005930",
            start_date=date(2026, 7, 10),
            end_date=date(2026, 7, 1),
        )


def test_get_latest_raises_when_instrument_missing():
    service = PriceDailyService(FakePriceRepository())

    with pytest.raises(InstrumentNotFoundError):
        service.get_latest(
            exchange_code="KRX",
            symbol="005930",
        )
