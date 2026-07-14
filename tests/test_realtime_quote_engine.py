import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.realtime.bus import RealtimeQuoteBus
from stock_platform.realtime.cache import RealtimeQuoteCache
from stock_platform.realtime.models import (
    MarketEventType,
    RealtimeQuote,
)
from stock_platform.realtime.upbit_client import (
    UpbitRealtimeClient,
)


def _quote() -> RealtimeQuote:
    now = datetime.now(timezone.utc)
    return RealtimeQuote(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        event_type=MarketEventType.TICKER,
        trade_price=Decimal("150000000"),
        opening_price=None,
        high_price=None,
        low_price=None,
        previous_close_price=None,
        change_price=None,
        change_rate=Decimal("0.01"),
        accumulated_volume=None,
        trade_volume=None,
        event_time=now,
        received_at=now,
        source_code="TEST",
    )


def test_upbit_payload_conversion() -> None:
    quote = UpbitRealtimeClient._to_quote(
        {
            "type": "ticker",
            "code": "KRW-BTC",
            "trade_price": 150000000,
            "opening_price": 149000000,
            "high_price": 151000000,
            "low_price": 148000000,
            "prev_closing_price": 149500000,
            "signed_change_price": 500000,
            "signed_change_rate": 0.00334448,
            "acc_trade_volume_24h": 123.45,
            "trade_volume": 0.001,
            "timestamp": 1784064000000,
        }
    )

    assert quote.exchange_code == "UPBIT"
    assert quote.symbol == "KRW-BTC"
    assert quote.trade_price == Decimal("150000000")
    assert quote.source_code == "UPBIT_WEBSOCKET"


def test_cache_stores_latest_quote() -> None:
    async def run() -> None:
        cache = RealtimeQuoteCache()
        quote = _quote()

        await cache.set(quote)

        loaded = await cache.get(
            exchange_code="UPBIT",
            symbol="KRW-BTC",
        )

        assert loaded == quote
        assert len(await cache.list_all()) == 1

    asyncio.run(run())


def test_bus_publishes_to_subscriber() -> None:
    async def run() -> None:
        bus = RealtimeQuoteBus()

        async def receive():
            async for item in bus.subscribe():
                return item

        task = asyncio.create_task(receive())
        await asyncio.sleep(0)
        await bus.publish(_quote())

        received = await asyncio.wait_for(
            task,
            timeout=1,
        )

        assert received.symbol == "KRW-BTC"

    asyncio.run(run())
