"""Focused tests: Kiwoom market realtime runtime start + concurrent isolation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.realtime.kiwoom_market_realtime_runtime import (
    KiwoomMarketRealtimeRuntime,
)


@pytest.mark.asyncio
async def test_market_realtime_start_blocks_when_process_market_mock() -> None:
    runtime = KiwoomMarketRealtimeRuntime()
    with patch(
        "stock_platform.realtime.kiwoom_market_realtime_runtime.get_settings",
        return_value=SimpleNamespace(
            kiwoom_market_data_is_mock=True,
            kiwoom_use_mock=True,
            kiwoom_market_realtime_auto_start=False,
        ),
    ):
        out = await runtime.start(
            user_broker_account_id=99,
            symbols=["034310"],
            require_real=True,
        )
    assert out["started"] is False
    assert out["reason"] == "MARKET_DATA_MOCK_FORBIDDEN"


@pytest.mark.asyncio
async def test_market_realtime_start_blocks_mock_credential() -> None:
    runtime = KiwoomMarketRealtimeRuntime()
    session = MagicMock()
    factory = MagicMock(return_value=session)
    resolved = MagicMock()
    order_cfg = SimpleNamespace(use_mock=True)

    with (
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.get_settings",
            return_value=SimpleNamespace(
                kiwoom_market_data_is_mock=False,
                kiwoom_use_mock=True,
                kiwoom_market_realtime_auto_start=False,
            ),
        ),
        patch(
            "stock_platform.database.session.get_session_factory",
            return_value=factory,
        ),
        patch(
            "stock_platform.broker.credential_adapter_factory.resolve_uba_credential",
            return_value=resolved,
        ),
        patch(
            "stock_platform.broker.credential_adapter_factory.build_kiwoom_order_config_from_vault",
            return_value=order_cfg,
        ),
    ):
        out = await runtime.start(
            user_broker_account_id=99,
            symbols=["034310"],
            require_real=True,
        )
    assert out["started"] is False
    assert out["reason"] == "UBA_CREDENTIAL_IS_MOCK"
    session.close.assert_called()


@pytest.mark.asyncio
async def test_market_realtime_start_spawns_task_and_stop_clears() -> None:
    runtime = KiwoomMarketRealtimeRuntime()
    session = MagicMock()
    factory = MagicMock(return_value=session)
    resolved = MagicMock()
    order_cfg = SimpleNamespace(use_mock=False)

    fake_client = MagicMock()
    fake_client.subscribe_symbols = MagicMock()
    fake_client.run_forever = AsyncMock(side_effect=asyncio.Event().wait)
    fake_client.shutdown = AsyncMock()
    fake_client.status = MagicMock(
        return_value={
            "connected": True,
            "subscription_count": 1,
            "event_count": 0,
            "last_event_at": None,
            "environment": "REAL",
        }
    )

    with (
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.get_settings",
            return_value=SimpleNamespace(
                kiwoom_market_data_is_mock=False,
                kiwoom_use_mock=True,
                kiwoom_market_realtime_auto_start=False,
            ),
        ),
        patch(
            "stock_platform.database.session.get_session_factory",
            return_value=factory,
        ),
        patch(
            "stock_platform.broker.credential_adapter_factory.resolve_uba_credential",
            return_value=resolved,
        ),
        patch(
            "stock_platform.broker.credential_adapter_factory.build_kiwoom_order_config_from_vault",
            return_value=order_cfg,
        ),
        patch(
            "stock_platform.broker.kiwoom.token_client.KiwoomTokenClient",
        ),
        patch(
            "stock_platform.broker.kiwoom.token_cache.KiwoomTokenCache",
        ),
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.KiwoomMarketRealtimeClient",
            return_value=fake_client,
        ),
    ):
        started = await runtime.start(
            user_broker_account_id=42,
            symbols=["034310", "005930"],
            require_real=True,
        )
        assert started["started"] is True
        assert started["running"] is True
        assert started["user_broker_account_id"] == 42
        fake_client.subscribe_symbols.assert_called()

        stopped = await runtime.stop()
        assert stopped["stopped"] is True
        assert runtime.status()["running"] is False
        fake_client.shutdown.assert_awaited()
