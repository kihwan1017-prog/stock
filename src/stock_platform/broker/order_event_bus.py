from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from stock_platform.broker.kiwoom.ws_models import (
    KiwoomOrderExecutionEvent,
)


class BrokerOrderEventBus:
    def __init__(self, queue_size: int = 1000) -> None:
        self._queue_size = queue_size
        self._subscribers: set[
            asyncio.Queue[KiwoomOrderExecutionEvent]
        ] = set()

    async def publish(
        self,
        event: KiwoomOrderExecutionEvent,
    ) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.task_done()
                    queue.put_nowait(event)
                except (
                    asyncio.QueueEmpty,
                    asyncio.QueueFull,
                ):
                    self._subscribers.discard(queue)

    async def subscribe(
        self,
    ) -> AsyncIterator[KiwoomOrderExecutionEvent]:
        queue: asyncio.Queue[KiwoomOrderExecutionEvent] = (
            asyncio.Queue(maxsize=self._queue_size)
        )
        self._subscribers.add(queue)

        try:
            while True:
                event = await queue.get()
                try:
                    yield event
                finally:
                    queue.task_done()
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
