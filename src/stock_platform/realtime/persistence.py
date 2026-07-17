from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

import structlog

from stock_platform.database.session import get_session_factory
from stock_platform.markets.repository import (
    InstrumentRepository,
    OrderbookSnapshotRepository,
    QuoteSnapshotRepository,
    TradeTickRepository,
)
from stock_platform.markets.service import (
    InstrumentService,
    OrderbookSnapshotService,
    QuoteSnapshotService,
    TradeTickService,
)
from stock_platform.realtime.models import (
    RealtimeOrderbook,
    RealtimeQuote,
    RealtimeTrade,
)


logger = structlog.get_logger(__name__)


class PersistKind(StrEnum):
    QUOTE = "QUOTE"
    TRADE = "TRADE"
    ORDERBOOK = "ORDERBOOK"


@dataclass(frozen=True, slots=True)
class PersistEnvelope:
    kind: PersistKind
    payload: Any


class MarketDataPersistenceWorker:
    """
    실시간 수신과 DB 저장을 Queue로 분리한다.

    - queue full: drop + 카운트
    - DB 장애: bounded retry 후 포기
    """

    def __init__(
        self,
        *,
        max_queue_size: int = 5000,
        max_retries: int = 3,
        retry_delay_seconds: float = 0.5,
        enabled: bool = True,
    ) -> None:
        self._queue: asyncio.Queue[PersistEnvelope] = (
            asyncio.Queue(maxsize=max_queue_size)
        )
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._enabled = enabled
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

        self._enqueued = 0
        self._persisted = 0
        self._dropped = 0
        self._failed = 0
        self._last_error: str | None = None
        self._last_persisted_at: datetime | None = None

    async def start(self) -> None:
        if not self._enabled or self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="market-data-persistence",
        )
        logger.info("market_data_persistence_started")

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("market_data_persistence_stopped")

    def enqueue_quote(self, quote: RealtimeQuote) -> bool:
        return self._enqueue(
            PersistEnvelope(PersistKind.QUOTE, quote)
        )

    def enqueue_trade(self, trade: RealtimeTrade) -> bool:
        return self._enqueue(
            PersistEnvelope(PersistKind.TRADE, trade)
        )

    def enqueue_orderbook(
        self,
        orderbook: RealtimeOrderbook,
    ) -> bool:
        return self._enqueue(
            PersistEnvelope(PersistKind.ORDERBOOK, orderbook)
        )

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "running": self._task is not None
            and not self._task.done(),
            "queue_size": self._queue.qsize(),
            "enqueued": self._enqueued,
            "persisted": self._persisted,
            "dropped": self._dropped,
            "failed": self._failed,
            "last_error": self._last_error,
            "last_persisted_at": (
                self._last_persisted_at.isoformat()
                if self._last_persisted_at
                else None
            ),
        }

    def _enqueue(self, envelope: PersistEnvelope) -> bool:
        if not self._enabled:
            return False

        try:
            self._queue.put_nowait(envelope)
            self._enqueued += 1
            return True
        except asyncio.QueueFull:
            self._dropped += 1
            logger.warning(
                "market_data_persistence_dropped",
                kind=envelope.kind.value,
                queue_size=self._queue.qsize(),
            )
            return False

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                envelope = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise

            await self._persist_with_retry(envelope)

    async def _persist_with_retry(
        self,
        envelope: PersistEnvelope,
    ) -> None:
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                await asyncio.to_thread(
                    self._persist_sync,
                    envelope,
                )
                self._persisted += 1
                self._last_persisted_at = datetime.now(timezone.utc)
                self._last_error = None
                return
            except Exception as exc:
                last_error = exc
                self._last_error = str(exc)[:500]
                logger.warning(
                    "market_data_persistence_retry",
                    kind=envelope.kind.value,
                    attempt=attempt,
                    error=self._last_error,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(
                        self._retry_delay_seconds * attempt
                    )

        self._failed += 1
        logger.error(
            "market_data_persistence_failed",
            kind=envelope.kind.value,
            error=str(last_error),
        )

    def _persist_sync(self, envelope: PersistEnvelope) -> None:
        session = get_session_factory()()
        try:
            instrument_service = InstrumentService(
                InstrumentRepository(session)
            )

            if envelope.kind == PersistKind.QUOTE:
                quote: RealtimeQuote = envelope.payload
                QuoteSnapshotService(
                    QuoteSnapshotRepository(session),
                    instrument_service,
                ).upsert_from_quote(
                    exchange_code=quote.exchange_code,
                    symbol=quote.symbol,
                    trade_price=quote.trade_price,
                    quoted_at=quote.event_time,
                    source=quote.source_code,
                    change_price=quote.change_price,
                    change_rate=quote.change_rate,
                    volume=quote.accumulated_volume,
                    asset_type=self._asset_type(quote.exchange_code),
                )
                return

            if envelope.kind == PersistKind.TRADE:
                trade: RealtimeTrade = envelope.payload
                TradeTickService(
                    TradeTickRepository(session),
                    instrument_service,
                ).save_many(
                    exchange_code=trade.exchange_code,
                    symbol=trade.symbol,
                    source=trade.source_code,
                    rows=[
                        {
                            "trade_id": trade.trade_id,
                            "price": trade.price,
                            "quantity": trade.quantity,
                            "side": trade.side,
                            "traded_at": trade.traded_at,
                        }
                    ],
                    asset_type=self._asset_type(trade.exchange_code),
                )
                return

            if envelope.kind == PersistKind.ORDERBOOK:
                book: RealtimeOrderbook = envelope.payload
                OrderbookSnapshotService(
                    OrderbookSnapshotRepository(session),
                    instrument_service,
                ).save(
                    exchange_code=book.exchange_code,
                    symbol=book.symbol,
                    captured_at=book.captured_at,
                    bids=book.bids,
                    asks=book.asks,
                    source=book.source_code,
                    asset_type=self._asset_type(book.exchange_code),
                )
                return

            raise ValueError(f"Unknown persist kind: {envelope.kind}")
        finally:
            session.close()

    @staticmethod
    def _asset_type(exchange_code: str) -> str:
        if exchange_code.upper() == "UPBIT":
            return "CRYPTO"
        return "STOCK"


# 프로세스 전역 워커 (lifecycle에서 start/stop)
market_data_persistence_worker = MarketDataPersistenceWorker()
