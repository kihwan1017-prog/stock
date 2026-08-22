from __future__ import annotations

import asyncio
from typing import Any

from stock_platform.realtime.bus import RealtimeQuoteBus
from stock_platform.realtime.cache import RealtimeQuoteCache
from stock_platform.realtime.models import (
    RealtimeOrderbook,
    RealtimeQuote,
    RealtimeTrade,
)
from stock_platform.realtime.persistence import (
    market_data_persistence_worker,
)
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
        # request cancel scope에서도 task 참조 유지
        self._background_tasks: set[asyncio.Task] = set()
        self.persistence = market_data_persistence_worker

    async def handle_quote(
        self,
        quote: RealtimeQuote,
    ) -> None:
        await self.cache.set(quote)
        await self.bus.publish(quote)
        self.persistence.enqueue_quote(quote)

    async def handle_trade(
        self,
        trade: RealtimeTrade,
    ) -> None:
        self.persistence.enqueue_trade(trade)

    async def handle_orderbook(
        self,
        orderbook: RealtimeOrderbook,
    ) -> None:
        self.persistence.enqueue_orderbook(orderbook)

    def _track_task(self, task: asyncio.Task) -> asyncio.Task:
        """strong-ref로 GC 방지 + done 시 자동 제거."""

        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _discard_client(self, client_id: str) -> None:
        normalized = client_id.upper()
        client = self._clients.pop(normalized, None)
        task = self._tasks.pop(normalized, None)
        if client is not None:
            await client.stop()
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _wait_until_connected(
        self,
        *,
        client: UpbitRealtimeClient,
        task: asyncio.Task,
        timeout_seconds: float,
    ) -> bool:
        """최초 연결까지 짧게 대기 — start 응답의 connected 신뢰성."""

        if timeout_seconds <= 0:
            return bool(client.status().get("connected"))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(timeout_seconds)
        while loop.time() < deadline:
            if bool(client.status().get("connected")):
                return True
            if task.done():
                return False
            await asyncio.sleep(0.05)
        return bool(client.status().get("connected"))

    async def start_upbit(
        self,
        *,
        symbols: list[str],
        channels: list[str] | None = None,
        connect_timeout_seconds: float = 5.0,
    ) -> dict:
        client_id = "UPBIT"
        existing_task = self._tasks.get(client_id)
        existing_client = self._clients.get(client_id)
        requested = [
            str(s).strip().upper() for s in (symbols or []) if str(s).strip()
        ]

        # 이미 살아있는 task — 심볼 누락 시 union restart (OPEN position 보호)
        if existing_task is not None and not existing_task.done():
            if existing_client is None:
                await self._discard_client(client_id)
            else:
                current = [
                    str(x).upper()
                    for x in (existing_client.status().get("symbols") or [])
                    if x
                ]
                missing = [s for s in requested if s not in current]
                if not missing:
                    connected = await self._wait_until_connected(
                        client=existing_client,
                        task=existing_task,
                        timeout_seconds=connect_timeout_seconds,
                    )
                    return {
                        **existing_client.status(),
                        "already_running": True,
                        "already_covering": True,
                        "task_running": True,
                        "connected_waited": connected,
                    }
                # expand: stop 후 union으로 재기동
                symbols = list(dict.fromkeys([*current, *requested]))
                await self._discard_client(client_id)

        # 종료된 stale task/client 정리 후 재시작
        if (
            self._tasks.get(client_id) is not None
            or self._clients.get(client_id) is not None
        ):
            await self._discard_client(client_id)

        if not symbols:
            raise ValueError("symbols must not be empty")

        client = UpbitRealtimeClient(
            symbols=symbols,
            quote_handler=self.handle_quote,
            trade_handler=self.handle_trade,
            orderbook_handler=self.handle_orderbook,
            channels=channels
            or ["ticker", "trade", "orderbook"],
        )
        task = self._track_task(
            asyncio.create_task(
                client.run_forever(),
                name="upbit-realtime",
            )
        )

        self._clients[client_id] = client
        self._tasks[client_id] = task

        connected = await self._wait_until_connected(
            client=client,
            task=task,
            timeout_seconds=connect_timeout_seconds,
        )
        return {
            **client.status(),
            "expanded": True,
            "already_running": False,
            "task_running": not task.done(),
            "connected_waited": connected,
        }

    async def stop(self, client_id: str) -> None:
        await self._discard_client(client_id)

    async def stop_all(self) -> None:
        for client_id in list(self._tasks):
            await self.stop(client_id)

    async def status(self) -> dict:
        clients: dict[str, Any] = {}
        for client_id, client in self._clients.items():
            task = self._tasks.get(client_id)
            clients[client_id] = {
                **client.status(),
                "task_running": bool(task is not None and not task.done()),
                "task_done": bool(task is not None and task.done()),
            }
        return {
            "clients": clients,
            "cache": await self.cache.health(),
            "subscriber_count": self.bus.subscriber_count,
            "persistence": self.persistence.status(),
        }


realtime_manager = RealtimeMarketDataManager()
