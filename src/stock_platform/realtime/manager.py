from __future__ import annotations

import asyncio
from typing import Any

from stock_platform.realtime.bus import RealtimeQuoteBus
from stock_platform.realtime.cache import RealtimeQuoteCache
from stock_platform.realtime.models import RealtimeQuote
from stock_platform.realtime.upbit_client import (
    UpbitRealtimeClient,
)


class RealtimeMarketDataManager:
    """실시간 클라이언트의 시작·종료·상태를 관리한다."""

    def __init__(self) -> None:
        self.bus = RealtimeQuoteBus()
        self.cache = RealtimeQuoteCache()
        self._clients: dict[str, Any] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def handle_quote(
        self,
        quote: RealtimeQuote,
    ) -> None:
        await self.cache.set(quote)
        await self.bus.publish(quote)

    async def start_upbit(
        self,
        *,
        symbols: list[str],
    ) -> dict:
        client_id = "UPBIT"

        if client_id in self._tasks:
            raise ValueError(
                "UPBIT realtime client is already running"
            )

        client = UpbitRealtimeClient(
            symbols=symbols,
            handler=self.handle_quote,
        )
        task = asyncio.create_task(
            client.run_forever(),
            name="upbit-realtime",
        )

        self._clients[client_id] = client
        self._tasks[client_id] = task

        return client.status()

    async def stop(self, client_id: str) -> None:
        normalized = client_id.upper()
        client = self._clients.get(normalized)
        task = self._tasks.get(normalized)

        if client is not None:
            await client.stop()

        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._clients.pop(normalized, None)
        self._tasks.pop(normalized, None)

    async def stop_all(self) -> None:
        for client_id in list(self._tasks):
            await self.stop(client_id)

    async def status(self) -> dict:
        return {
            "clients": {
                client_id: client.status()
                for client_id, client in self._clients.items()
            },
            "cache": await self.cache.health(),
            "subscriber_count": self.bus.subscriber_count,
        }


realtime_manager = RealtimeMarketDataManager()
