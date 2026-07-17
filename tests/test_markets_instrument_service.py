from datetime import date
from types import SimpleNamespace

import pytest

from stock_platform.markets.service import (
    InstrumentNotFoundError,
    InstrumentService,
    PriceDailyService,
)


class FakeInstrumentRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], SimpleNamespace] = {}
        self.next_id = 1

    def find(self, exchange_code: str, symbol: str):
        return self.rows.get((exchange_code, symbol))

    def list(self, *, exchange_code=None, active_only=True, limit=5000):
        values = list(self.rows.values())
        if exchange_code is not None:
            values = [
                item
                for item in values
                if item.exchange_code == exchange_code
            ]
        if active_only:
            values = [item for item in values if item.is_active]
        return values[:limit]

    def upsert_many(self, rows):
        for row in rows:
            key = (row["exchange_code"], row["symbol"])
            existing = self.rows.get(key)
            instrument_id = (
                existing.instrument_id
                if existing is not None
                else self.next_id
            )
            if existing is None:
                self.next_id += 1
            self.rows[key] = SimpleNamespace(
                instrument_id=instrument_id,
                **row,
            )
        return len(list(rows))


class FakePriceRepository:
    def __init__(self, instrument_repo: FakeInstrumentRepository):
        self.instrument_repo = instrument_repo
        self.prices: list[dict] = []

    def find_instrument(self, exchange_code: str, symbol: str):
        return self.instrument_repo.find(exchange_code, symbol)

    def find_latest(self, instrument_id: int):
        matched = [
            row
            for row in self.prices
            if row["instrument_id"] == instrument_id
        ]
        return matched[-1] if matched else None

    def find_between(
        self,
        instrument_id: int,
        start_date: date,
        end_date: date,
    ):
        return [
            row
            for row in self.prices
            if row["instrument_id"] == instrument_id
            and start_date <= row["trade_date"] <= end_date
        ]

    def list_recent(self, instrument_id: int, *, limit: int = 200):
        matched = [
            row
            for row in self.prices
            if row["instrument_id"] == instrument_id
        ]
        return matched[-limit:]

    def upsert_many(self, rows):
        values = list(rows)
        self.prices.extend(values)
        return len(values)


def test_instrument_ensure_creates_missing_row() -> None:
    repo = FakeInstrumentRepository()
    service = InstrumentService(repo)  # type: ignore[arg-type]

    created = service.ensure(
        exchange_code="upbit",
        symbol="krw-btc",
        name="비트코인",
        asset_type="CRYPTO",
    )

    assert created.exchange_code == "UPBIT"
    assert created.symbol == "KRW-BTC"
    assert created.name == "비트코인"


def test_price_save_many_ensures_instrument() -> None:
    instrument_repo = FakeInstrumentRepository()
    instrument_service = InstrumentService(
        instrument_repo  # type: ignore[arg-type]
    )
    price_service = PriceDailyService(
        FakePriceRepository(instrument_repo),  # type: ignore[arg-type]
        instrument_service=instrument_service,
    )

    saved = price_service.save_many(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        source="UPBIT",
        rows=[
            {
                "trade_date": date(2026, 7, 1),
                "open_price": "100",
                "high_price": "110",
                "low_price": "90",
                "close_price": "105",
                "volume": "1",
                "trade_value": "105",
            }
        ],
    )

    assert saved == 1
    assert instrument_repo.find("UPBIT", "KRW-BTC") is not None


def test_price_save_many_raises_without_ensure() -> None:
    service = PriceDailyService(
        FakePriceRepository(FakeInstrumentRepository())  # type: ignore[arg-type]
    )

    with pytest.raises(InstrumentNotFoundError):
        service.save_many(
            exchange_code="UPBIT",
            symbol="KRW-BTC",
            source="UPBIT",
            rows=[],
            ensure_instrument=False,
        )
