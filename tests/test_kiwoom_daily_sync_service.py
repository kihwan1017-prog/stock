import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.collectors.kiwoom.dto import DailyPriceDTO
from stock_platform.collectors.kiwoom.sync_service import (
    KiwoomDailySyncService,
)


class FakeCollector:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def collect(self, **kwargs):
        self.calls.append(kwargs)

        return [
            DailyPriceDTO(
                trade_date=date(2026, 7, 10),
                open_price=Decimal("86000"),
                high_price=Decimal("87500"),
                low_price=Decimal("85500"),
                close_price=Decimal("87200"),
                volume=Decimal("12000000"),
                trade_value=Decimal("1046400000000"),
                change_rate=Decimal("1.28"),
            )
        ]


class FakePriceService:
    def __init__(self, latest=None) -> None:
        self.latest = latest
        self.saved: list[dict] = []

    def get_latest(self, exchange_code: str, symbol: str):
        return self.latest

    def save_many(
        self,
        exchange_code: str,
        symbol: str,
        source: str,
        rows: list[dict],
        **kwargs,
    ) -> int:
        self.saved.append(
            {
                "exchange_code": exchange_code,
                "symbol": symbol,
                "source": source,
                "rows": rows,
                "kwargs": kwargs,
            }
        )
        return len(rows)


def test_sync_collects_and_saves() -> None:
    collector = FakeCollector()
    price_service = FakePriceService()
    service = KiwoomDailySyncService(
        collector=collector,  # type: ignore[arg-type]
        price_service=price_service,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.sync(
            symbol="005930",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 10),
        )
    )

    assert result.collected_count == 1
    assert result.saved_count == 1
    assert price_service.saved[0]["source"] == "KIWOOM"
    assert price_service.saved[0]["rows"][0]["trade_date"] == date(
        2026,
        7,
        10,
    )


def test_sync_resumes_after_latest_date() -> None:
    collector = FakeCollector()
    price_service = FakePriceService(
        latest=SimpleNamespace(trade_date=date(2026, 7, 8))
    )
    service = KiwoomDailySyncService(
        collector=collector,  # type: ignore[arg-type]
        price_service=price_service,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.sync(
            symbol="005930",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 10),
            resume=True,
        )
    )

    assert result.requested_start_date == date(2026, 7, 9)
    assert collector.calls[0]["start_date"] == date(2026, 7, 9)


def test_sync_skips_when_already_up_to_date() -> None:
    collector = FakeCollector()
    price_service = FakePriceService(
        latest=SimpleNamespace(trade_date=date(2026, 7, 10))
    )
    service = KiwoomDailySyncService(
        collector=collector,  # type: ignore[arg-type]
        price_service=price_service,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.sync(
            symbol="005930",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 10),
            resume=True,
        )
    )

    assert result.collected_count == 0
    assert result.saved_count == 0
    assert collector.calls == []
