from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from stock_platform.realtime.bus import RealtimeQuoteBus
from stock_platform.realtime.cache import RealtimeQuoteCache
from stock_platform.realtime.models import (
    MarketEventType,
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


def _quote_from_trade(trade: RealtimeTrade) -> RealtimeQuote | None:
    """체결 틱 → QuoteSnapshot 갱신용 (strategy bus 미발행)."""

    try:
        price = Decimal(str(trade.price))
    except Exception:  # noqa: BLE001
        return None
    if price <= 0:
        return None
    received = trade.received_at or datetime.now(timezone.utc)
    # freshness는 수신 시각 기준 — trade gap에서도 최근 확인을 반영
    return RealtimeQuote(
        exchange_code=str(trade.exchange_code or "UPBIT").upper(),
        symbol=str(trade.symbol or "").upper(),
        event_type=MarketEventType.TICKER,
        trade_price=price,
        opening_price=None,
        high_price=None,
        low_price=None,
        previous_close_price=None,
        change_price=None,
        change_rate=None,
        accumulated_volume=None,
        trade_volume=Decimal(str(trade.quantity))
        if trade.quantity is not None
        else None,
        event_time=received,
        received_at=received,
        source_code="UPBIT_WEBSOCKET_TRADE",
    )


def _quote_from_orderbook(book: RealtimeOrderbook) -> RealtimeQuote | None:
    """호가 갱신 → OPEN 보호용 QuoteSnapshot (체결 공백 보완)."""

    bid = None
    ask = None
    try:
        if book.bids:
            bid = Decimal(str(book.bids[0].get("price")))
        if book.asks:
            ask = Decimal(str(book.asks[0].get("price")))
    except Exception:  # noqa: BLE001
        return None
    if bid is None and ask is None:
        return None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / Decimal("2")
    elif bid is not None and bid > 0:
        mid = bid
    elif ask is not None and ask > 0:
        mid = ask
    else:
        return None
    received = book.received_at or datetime.now(timezone.utc)
    return RealtimeQuote(
        exchange_code=str(book.exchange_code or "UPBIT").upper(),
        symbol=str(book.symbol or "").upper(),
        event_type=MarketEventType.TICKER,
        trade_price=mid,
        opening_price=None,
        high_price=None,
        low_price=None,
        previous_close_price=None,
        change_price=None,
        change_rate=None,
        accumulated_volume=None,
        trade_volume=None,
        event_time=received,
        received_at=received,
        source_code="UPBIT_WEBSOCKET_ORDERBOOK",
        bid=bid,
        ask=ask,
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
        # trade 채널만 오고 ticker가 공백일 때 Exit QuoteSnapshot 보완
        derived = _quote_from_trade(trade)
        if derived is not None:
            await self.cache.set(derived)
            self.persistence.enqueue_quote(derived)

    async def handle_orderbook(
        self,
        orderbook: RealtimeOrderbook,
    ) -> None:
        self.persistence.enqueue_orderbook(orderbook)
        # 체결 없는 구간에도 OPEN 심볼 호가로 Snapshot freshness 유지
        # strategy bus에는 올리지 않음 (MA 신호 오염 방지)
        derived = _quote_from_orderbook(orderbook)
        if derived is not None:
            await self.cache.set(derived)
            self.persistence.enqueue_quote(derived)

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
        wanted_channels = [
            str(c).strip().lower()
            for c in (channels or ["ticker", "trade", "orderbook"])
            if str(c).strip()
        ]
        if not wanted_channels:
            wanted_channels = ["ticker", "trade", "orderbook"]

        # 이미 살아있는 task — 심볼/채널 누락 시 union restart (OPEN 보호)
        if existing_task is not None and not existing_task.done():
            if existing_client is None:
                await self._discard_client(client_id)
            else:
                current = [
                    str(x).upper()
                    for x in (existing_client.status().get("symbols") or [])
                    if x
                ]
                current_channels = {
                    str(c).lower()
                    for c in (existing_client.status().get("channels") or [])
                    if c
                }
                missing = [s for s in requested if s not in current]
                missing_channels = [
                    c for c in wanted_channels if c not in current_channels
                ]
                if not missing and not missing_channels:
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
            channels=wanted_channels,
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
