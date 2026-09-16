"""Kiwoom market data failure — feed start race, health SoT, universe resolve."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.realtime.kiwoom_market_realtime_runtime import (
    KiwoomMarketRealtimeRuntime,
)
from stock_platform.trading.execution_stack_reconciliation import _FEED_OK


def test_feed_ok_includes_connecting() -> None:
    assert "CONNECTING" in _FEED_OK
    assert "REAL_FRESH" in _FEED_OK


def test_status_clears_connected_when_task_done() -> None:
    runtime = KiwoomMarketRealtimeRuntime()
    client = MagicMock()
    client.status.return_value = {
        "connected": True,
        "last_event_at": None,
        "symbols": ["034310"],
        "subscription_count": 1,
        "event_count": 0,
        "last_error": None,
    }
    runtime.bind(client)
    runtime._uba_id = 1381
    st = runtime.status()
    assert st["running"] is False
    assert st["connected"] is False


@pytest.mark.asyncio
async def test_concurrent_start_same_uba_does_not_cancel() -> None:
    """동시 start 가 기존 receive task 를 stop/cancel 하면 안 된다."""

    runtime = KiwoomMarketRealtimeRuntime()
    session = MagicMock()
    factory = MagicMock(return_value=session)
    resolved = MagicMock()
    resolved.credential_id = 1
    resolved.broker_code = "KIWOOM"
    order_cfg = SimpleNamespace(use_mock=False)

    hold = asyncio.Event()

    async def _run_forever() -> None:
        await hold.wait()

    fake_client = MagicMock()
    fake_client.subscribe_symbols = MagicMock()
    fake_client.run_forever = _run_forever
    fake_client.shutdown = AsyncMock()
    fake_client.status = MagicMock(
        return_value={
            "connected": True,
            "subscription_count": 1,
            "event_count": 0,
            "last_event_at": None,
            "environment": "REAL",
            "last_error": None,
            "symbols": ["034310"],
        }
    )

    with (
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.get_settings",
            return_value=SimpleNamespace(
                kiwoom_market_data_is_mock=False,
                kiwoom_market_data_use_mock=False,
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
        patch("stock_platform.broker.kiwoom.token_client.KiwoomTokenClient"),
        patch("stock_platform.broker.kiwoom.token_cache.KiwoomTokenCache"),
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.KiwoomMarketRealtimeClient",
            return_value=fake_client,
        ),
    ):
        first, second = await asyncio.gather(
            runtime.start(
                user_broker_account_id=1381,
                symbols=["034310"],
                require_real=True,
                connect_wait_seconds=0.3,
            ),
            runtime.start(
                user_broker_account_id=1381,
                symbols=["034310"],
                require_real=True,
                connect_wait_seconds=0.3,
            ),
        )
        assert first["started"] is True or second["started"] is True
        assert runtime.status()["running"] is True
        fake_client.shutdown.assert_not_awaited()
        hold.set()
        await runtime.stop()


@pytest.mark.asyncio
async def test_restore_all_skips_when_not_regular() -> None:
    from stock_platform.trading.kiwoom_unattended_stack_restore import (
        restore_all_active_unattended_kiwoom_leases,
    )

    session = MagicMock()
    factory = MagicMock(return_value=session)
    with (
        patch(
            "stock_platform.database.session.get_session_factory",
            return_value=factory,
        ),
        patch(
            "stock_platform.trading.market_hours_authorization.krx_market_hours_state",
            return_value={
                "in_regular_session": False,
                "session_type": "CLOSED",
            },
        ),
    ):
        out = await restore_all_active_unattended_kiwoom_leases()
    assert out["skipped"] is True
    assert out["reason"] == "NOT_REGULAR_SESSION"
    session.close.assert_called()


def test_universe_resolve_uses_strategy_link() -> None:
    from stock_platform.trading.kiwoom_funnel_observability import (
        _resolve_fixed_symbols,
    )

    session = MagicMock()
    link = SimpleNamespace(strategy_id=99)
    session.scalar.return_value = link

    with (
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime"
        ) as kmr,
        patch(
            "stock_platform.trading.kiwoom_unattended_stack_restore._resolve_kiwoom_stack_feed_symbols",
            return_value=["034310"],
        ) as resolve,
    ):
        kmr.status.return_value = {
            "user_broker_account_id": 999,
            "running": False,
            "client": {},
        }
        out = _resolve_fixed_symbols(session, user_broker_account_id=1381)

    assert out == ["034310"]
    assert resolve.call_args.kwargs.get("strategy_id") == 99


@pytest.mark.asyncio
async def test_second_start_same_uba_is_idempotent() -> None:
    runtime = KiwoomMarketRealtimeRuntime()
    session = MagicMock()
    factory = MagicMock(return_value=session)
    resolved = MagicMock()
    resolved.credential_id = 1
    resolved.broker_code = "KIWOOM"
    order_cfg = SimpleNamespace(use_mock=False)
    hold = asyncio.Event()

    async def _run_forever() -> None:
        await hold.wait()

    fake_client = MagicMock()
    fake_client.subscribe_symbols = MagicMock()
    fake_client.run_forever = _run_forever
    fake_client.shutdown = AsyncMock()
    fake_client.status = MagicMock(
        return_value={
            "connected": False,
            "subscription_count": 1,
            "event_count": 0,
            "last_event_at": None,
            "environment": "REAL",
            "last_error": None,
            "symbols": ["034310"],
        }
    )

    with (
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.get_settings",
            return_value=SimpleNamespace(
                kiwoom_market_data_is_mock=False,
                kiwoom_market_data_use_mock=False,
                kiwoom_use_mock=False,
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
        patch("stock_platform.broker.kiwoom.token_client.KiwoomTokenClient"),
        patch("stock_platform.broker.kiwoom.token_cache.KiwoomTokenCache"),
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.KiwoomMarketRealtimeClient",
            return_value=fake_client,
        ),
    ):
        a = await runtime.start(
            user_broker_account_id=1381,
            symbols=["034310"],
            require_real=True,
            connect_wait_seconds=0.2,
        )
        b = await runtime.start(
            user_broker_account_id=1381,
            symbols=["034310"],
            require_real=True,
            connect_wait_seconds=0.2,
        )
        assert a["started"] is True
        assert b["started"] is True
        assert b.get("already_running") is True
        assert runtime.status()["running"] is True
        hold.set()
        await runtime.stop()
