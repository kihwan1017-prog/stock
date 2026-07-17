import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.realtime.models import (
    MarketEventType,
    RealtimeQuote,
)
from stock_platform.realtime.persistence import (
    MarketDataPersistenceWorker,
    PersistEnvelope,
    PersistKind,
)


def _quote() -> RealtimeQuote:
    now = datetime.now(timezone.utc)
    return RealtimeQuote(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        event_type=MarketEventType.TICKER,
        trade_price=Decimal("100"),
        opening_price=None,
        high_price=None,
        low_price=None,
        previous_close_price=None,
        change_price=None,
        change_rate=None,
        accumulated_volume=None,
        trade_volume=None,
        event_time=now,
        received_at=now,
        source_code="TEST",
    )


def test_persistence_drops_when_queue_full() -> None:
    worker = MarketDataPersistenceWorker(max_queue_size=1)

    assert worker.enqueue_quote(_quote()) is True
    assert worker.enqueue_quote(_quote()) is False
    assert worker.status()["dropped"] == 1


def test_persistence_retries_then_fails() -> None:
    worker = MarketDataPersistenceWorker(
        max_retries=2,
        retry_delay_seconds=0,
    )

    def boom(_envelope: PersistEnvelope) -> None:
        raise RuntimeError("db down")

    worker._persist_sync = boom  # type: ignore[method-assign]

    async def run() -> None:
        await worker._persist_with_retry(
            PersistEnvelope(PersistKind.QUOTE, _quote())
        )

    asyncio.run(run())
    assert worker.status()["failed"] == 1
