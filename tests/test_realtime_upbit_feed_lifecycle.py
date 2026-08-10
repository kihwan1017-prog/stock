"""Upbit Quote Feed start lifecycle — 실주문/LIVE 없음."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from stock_platform.realtime.manager import RealtimeMarketDataManager
from stock_platform.realtime.upbit_client import UpbitRealtimeClient


@pytest.mark.asyncio
async def test_start_upbit_waits_for_connected_and_is_idempotent() -> None:
    manager = RealtimeMarketDataManager()

    class _FakeClient:
        def __init__(self, **kwargs) -> None:
            self._connected = False
            self._stopped = False
            self.symbols = kwargs.get("symbols") or []
            self.channels = kwargs.get("channels") or []

        async def run_forever(self) -> None:
            await asyncio.sleep(0.05)
            self._connected = True
            while not self._stopped:
                await asyncio.sleep(0.05)

        async def stop(self) -> None:
            self._stopped = True

        def status(self) -> dict:
            return {
                "exchange_code": "UPBIT",
                "connected": self._connected,
                "connecting": not self._connected and not self._stopped,
                "running": self._connected or not self._stopped,
                "symbols": self.symbols,
                "channels": self.channels,
                "received_count": 0,
                "reconnect_count": 0,
                "last_error": None,
            }

    with patch(
        "stock_platform.realtime.manager.UpbitRealtimeClient",
        _FakeClient,
    ):
        first = await manager.start_upbit(
            symbols=["KRW-XRP"],
            channels=["ticker"],
            connect_timeout_seconds=1.0,
        )
        assert first["connected"] is True
        assert first["already_running"] is False
        assert first["task_running"] is True

        second = await manager.start_upbit(
            symbols=["KRW-XRP"],
            channels=["ticker"],
            connect_timeout_seconds=1.0,
        )
        assert second["already_running"] is True
        assert second["connected"] is True
        assert len(manager._clients) == 1

        await manager.stop_all()
        assert manager._clients == {}


@pytest.mark.asyncio
async def test_start_upbit_restarts_stale_done_task() -> None:
    manager = RealtimeMarketDataManager()

    class _DyingClient:
        def __init__(self, **kwargs) -> None:
            self.symbols = kwargs.get("symbols") or []
            self.channels = kwargs.get("channels") or []
            self._connected = False

        async def run_forever(self) -> None:
            return  # 즉시 종료 → stale task

        async def stop(self) -> None:
            return

        def status(self) -> dict:
            return {
                "exchange_code": "UPBIT",
                "connected": self._connected,
                "symbols": self.symbols,
                "channels": self.channels,
                "received_count": 0,
                "reconnect_count": 0,
                "last_error": None,
            }

    alive_started = {"n": 0}

    class _AliveClient(_DyingClient):
        async def run_forever(self) -> None:
            alive_started["n"] += 1
            self._connected = True
            await asyncio.Event().wait()

    with patch(
        "stock_platform.realtime.manager.UpbitRealtimeClient",
        _DyingClient,
    ):
        first = await manager.start_upbit(
            symbols=["KRW-XRP"],
            channels=["ticker"],
            connect_timeout_seconds=0.2,
        )
        assert first["task_running"] is False

    with patch(
        "stock_platform.realtime.manager.UpbitRealtimeClient",
        _AliveClient,
    ):
        second = await manager.start_upbit(
            symbols=["KRW-XRP"],
            channels=["ticker"],
            connect_timeout_seconds=0.5,
        )
        assert second["already_running"] is False
        assert second["connected"] is True
        assert alive_started["n"] == 1
        await manager.stop_all()


def test_upbit_subscribe_payload_shape() -> None:
    """Upbit 공식 ticker WS 구독 형식 유지 확인."""

    client = UpbitRealtimeClient(
        symbols=["KRW-XRP"],
        quote_handler=AsyncMock(),
        trade_handler=AsyncMock(),
        channels=["ticker", "trade"],
    )
    status = client.status()
    assert status["websocket_url"] == "wss://api.upbit.com/websocket/v1"
    assert status["symbols"] == ["KRW-XRP"]
    assert "ticker" in status["channels"]
    assert "last_connect_attempt" in status
    assert "connecting" in status
