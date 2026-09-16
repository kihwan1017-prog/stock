"""Upbit Quote Feed start lifecycle — 실주문/LIVE 없음."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.realtime.manager import RealtimeMarketDataManager
from stock_platform.realtime.upbit_client import UpbitRealtimeClient
from stock_platform.realtime.upbit_quote_feed_restore import (
    collect_upbit_symbols_from_hub,
    ensure_upbit_quote_feed_from_hub,
)


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


def test_collect_upbit_symbols_from_hub_filters_non_upbit() -> None:
    hub = SimpleNamespace(
        registry=SimpleNamespace(
            list_subscriptions=lambda: [
                {"broker_code": "UPBIT", "symbol": "KRW-XRP"},
                {"broker_code": "UPBIT", "symbol": "krw-xrp"},
                {"broker_code": "KIWOOM", "symbol": "005930"},
                {"broker_code": "UPBIT", "symbol": ""},
            ]
        )
    )
    with patch(
        "stock_platform.realtime.market_data_hub.get_realtime_market_data_hub",
        return_value=hub,
    ):
        assert collect_upbit_symbols_from_hub() == ["KRW-XRP"]


@pytest.mark.asyncio
async def test_ensure_upbit_quote_feed_noop_without_subscriptions() -> None:
    with patch(
        "stock_platform.realtime.upbit_quote_feed_restore.collect_upbit_symbols_from_hub",
        return_value=[],
    ):
        out = await ensure_upbit_quote_feed_from_hub(source="TEST")
    assert out["started"] is False
    assert out["reason"] == "NO_UPBIT_HUB_SUBSCRIPTIONS"


@pytest.mark.asyncio
async def test_ensure_upbit_quote_feed_starts_from_hub_symbols() -> None:
    manager = MagicMock()
    manager.start_upbit = AsyncMock(
        return_value={
            "connected": True,
            "running": True,
            "task_running": True,
            "already_running": False,
            "symbols": ["KRW-XRP"],
            "received_count": 1,
            "last_error": None,
        }
    )
    with (
        patch(
            "stock_platform.realtime.upbit_quote_feed_restore.collect_upbit_symbols_from_hub",
            return_value=["KRW-XRP"],
        ),
        patch(
            "stock_platform.realtime.manager.realtime_manager",
            manager,
        ),
    ):
        out = await ensure_upbit_quote_feed_from_hub(source="TEST")
    assert out["started"] is True
    assert out["symbols"] == ["KRW-XRP"]
    manager.start_upbit.assert_awaited_once()
    kwargs = manager.start_upbit.await_args.kwargs
    assert kwargs["symbols"] == ["KRW-XRP"]


def test_should_keep_upbit_when_hub_has_subscription() -> None:
    from stock_platform.realtime.live_runtime_control import (
        should_keep_upbit_on_krx_close,
    )

    settings = SimpleNamespace(
        realtime_upbit_shadow_auto_start_enabled=False,
        realtime_upbit_24x7_keep_on_krx_close=False,
    )
    with patch(
        "stock_platform.realtime.upbit_quote_feed_restore.hub_has_upbit_subscriptions",
        return_value=True,
    ):
        assert should_keep_upbit_on_krx_close(settings) is True
    with patch(
        "stock_platform.realtime.upbit_quote_feed_restore.hub_has_upbit_subscriptions",
        return_value=False,
    ):
        assert should_keep_upbit_on_krx_close(settings) is False
