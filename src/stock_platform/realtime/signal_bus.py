from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
)


class RealtimeSignalBus:
    """전략 신호를 주문 엔진 등 여러 소비자에게 전달한다."""

    def __init__(
        self,
        *,
        queue_size: int = 1_000,
    ) -> None:
        self._queue_size = queue_size
        self._subscribers: set[
            asyncio.Queue[RealtimeSignal]
        ] = set()

    async def publish(
        self,
        signal: RealtimeSignal,
    ) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(signal)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.task_done()
                    queue.put_nowait(signal)
                except (
                    asyncio.QueueEmpty,
                    asyncio.QueueFull,
                ):
                    self._subscribers.discard(queue)

    async def subscribe(
        self,
    ) -> AsyncIterator[RealtimeSignal]:
        queue: asyncio.Queue[RealtimeSignal] = (
            asyncio.Queue(
                maxsize=self._queue_size
            )
        )
        self._subscribers.add(queue)

        try:
            while True:
                signal = await queue.get()
                try:
                    yield signal
                finally:
                    queue.task_done()
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
