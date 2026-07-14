from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from stock_platform.realtime.models import RealtimeQuote


class RealtimeQuoteBus:
    """실시간 시세를 여러 소비자에게 전달하는 비동기 버스."""

    def __init__(self, *, queue_size: int = 10_000) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[RealtimeQuote]] = set()

    async def publish(self, quote: RealtimeQuote) -> None:
        dead: list[asyncio.Queue[RealtimeQuote]] = []

        for queue in self._subscribers:
            try:
                queue.put_nowait(quote)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.task_done()
                    queue.put_nowait(quote)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    dead.append(queue)

        for queue in dead:
            self._subscribers.discard(queue)

    async def subscribe(self) -> AsyncIterator[RealtimeQuote]:
        queue: asyncio.Queue[RealtimeQuote] = asyncio.Queue(
            maxsize=self._queue_size
        )
        self._subscribers.add(queue)

        try:
            while True:
                item = await queue.get()
                try:
                    yield item
                finally:
                    queue.task_done()
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
