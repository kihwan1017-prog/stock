import asyncio
from datetime import date
from types import SimpleNamespace

from stock_platform.collectors.upbit.batch_daily_sync_service import (
    UpbitKrwDailyBatchSyncService,
    years_ago,
)
from stock_platform.collectors.upbit.sync_service import (
    UpbitDailySyncResult,
)


class FakeInstrumentSync:
    def __init__(self) -> None:
        self.calls = 0

    async def sync(self, *, krw_only: bool = True):
        self.calls += 1
        return SimpleNamespace(saved_count=2)


class FakeInstrumentService:
    def list(self, **kwargs):
        return [
            SimpleNamespace(symbol="KRW-BTC"),
            SimpleNamespace(symbol="KRW-ETH"),
            SimpleNamespace(symbol="BTC-USDT"),
        ]


class FakeDailySync:
    def __init__(self, fail_markets: set[str] | None = None) -> None:
        self.fail_markets = fail_markets or set()
        self.calls: list[str] = []

    async def sync(self, *, market: str, **kwargs):
        self.calls.append(market)
        if market in self.fail_markets:
            raise RuntimeError(f"boom:{market}")

        return UpbitDailySyncResult(
            exchange_code="UPBIT",
            symbol=market,
            requested_start_date=date(2023, 7, 18),
            requested_end_date=date(2026, 7, 18),
            collected_count=3,
            saved_count=3,
        )


def test_years_ago_handles_leap_day() -> None:
    assert years_ago(date(2024, 2, 29), 1) == date(2023, 2, 28)


def test_batch_sync_filters_krw_and_retries() -> None:
    daily = FakeDailySync()
    eth_attempts = {"count": 0}
    original_sync = daily.sync

    async def flaky_sync(*, market: str, **kwargs):
        if market == "KRW-ETH":
            eth_attempts["count"] += 1
            if eth_attempts["count"] == 1:
                raise RuntimeError("temporary")
        return await original_sync(market=market, **kwargs)

    daily.sync = flaky_sync  # type: ignore[method-assign]

    service = UpbitKrwDailyBatchSyncService(
        instrument_sync=FakeInstrumentSync(),  # type: ignore[arg-type]
        daily_sync=daily,  # type: ignore[arg-type]
        instrument_service=FakeInstrumentService(),  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.sync(
            start_date=date(2023, 7, 1),
            end_date=date(2026, 7, 18),
            sync_instruments=True,
            max_retries=1,
            retry_delay_seconds=0,
        )
    )

    assert result.market_count == 2
    assert result.success_count == 2
    assert result.failed_count == 0
    assert result.instrument_synced == 2
    assert eth_attempts["count"] == 2
    assert "KRW-BTC" in daily.calls


def test_batch_sync_records_persistent_failures() -> None:
    daily = FakeDailySync(fail_markets={"KRW-BTC", "KRW-ETH"})

    service = UpbitKrwDailyBatchSyncService(
        instrument_sync=FakeInstrumentSync(),  # type: ignore[arg-type]
        daily_sync=daily,  # type: ignore[arg-type]
        instrument_service=FakeInstrumentService(),  # type: ignore[arg-type]
    )

    try:
        asyncio.run(
            service.sync(
                start_date=date(2023, 7, 1),
                end_date=date(2026, 7, 18),
                sync_instruments=False,
                max_retries=0,
                retry_delay_seconds=0,
            )
        )
        raised = False
    except RuntimeError:
        raised = True

    assert raised is True
