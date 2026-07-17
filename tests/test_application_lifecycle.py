import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from stock_platform.api.lifecycle import ApplicationLifecycle


@pytest.fixture
def lifecycle() -> ApplicationLifecycle:
    return ApplicationLifecycle()


def test_startup_is_idempotent(lifecycle: ApplicationLifecycle) -> None:
    with patch(
        "stock_platform.api.lifecycle.validate_startup_settings"
    ), patch(
        "stock_platform.api.lifecycle.verify_database_connection",
        new=AsyncMock(),
    ), patch(
        "stock_platform.api.lifecycle.broker_recovery_manager.recover",
        new=AsyncMock(return_value={"success": True}),
    ), patch.object(
        lifecycle,
        "_startup_strategy_runtime",
        new=AsyncMock(),
    ), patch.object(
        lifecycle,
        "_start_schedulers",
        new=AsyncMock(),
    ):
        asyncio.run(lifecycle.startup())
        asyncio.run(lifecycle.startup())

    assert lifecycle.started is True


def test_shutdown_is_idempotent(lifecycle: ApplicationLifecycle) -> None:
    lifecycle._started = True

    with patch.object(
        lifecycle,
        "_shutdown_schedulers",
        new=AsyncMock(),
    ), patch.object(
        lifecycle,
        "_shutdown_realtime_services",
        new=AsyncMock(),
    ), patch(
        "stock_platform.api.lifecycle.dynamic_strategy_runtime_manager.clear",
        new=AsyncMock(),
    ):
        asyncio.run(lifecycle.shutdown())
        asyncio.run(lifecycle.shutdown())

    assert lifecycle.started is False


def test_startup_continues_when_optional_phase_fails(
    lifecycle: ApplicationLifecycle,
) -> None:
    with patch(
        "stock_platform.api.lifecycle.validate_startup_settings"
    ), patch(
        "stock_platform.api.lifecycle.verify_database_connection",
        new=AsyncMock(),
    ), patch(
        "stock_platform.api.lifecycle.broker_recovery_manager.recover",
        new=AsyncMock(side_effect=RuntimeError("recovery failed")),
    ), patch.object(
        lifecycle,
        "_startup_strategy_runtime",
        new=AsyncMock(),
    ) as strategy_startup, patch.object(
        lifecycle,
        "_start_schedulers",
        new=AsyncMock(),
    ) as start_schedulers:
        asyncio.run(lifecycle.startup())

    strategy_startup.assert_awaited_once()
    start_schedulers.assert_awaited_once()
    assert lifecycle.started is True


def test_startup_stops_when_database_check_fails(
    lifecycle: ApplicationLifecycle,
) -> None:
    with patch(
        "stock_platform.api.lifecycle.validate_startup_settings"
    ), patch(
        "stock_platform.api.lifecycle.verify_database_connection",
        new=AsyncMock(
            side_effect=RuntimeError("database unavailable")
        ),
    ), patch.object(
        lifecycle,
        "_start_schedulers",
        new=AsyncMock(),
    ) as start_schedulers:
        with pytest.raises(RuntimeError, match="database unavailable"):
            asyncio.run(lifecycle.startup())

    start_schedulers.assert_not_called()
    assert lifecycle.started is False


def test_startup_order(lifecycle: ApplicationLifecycle) -> None:
    call_order: list[str] = []

    async def database_check() -> None:
        call_order.append("database")

    async def broker_recovery() -> None:
        call_order.append("broker")

    async def strategy_runtime() -> None:
        call_order.append("strategy")

    async def start_schedulers() -> None:
        call_order.append("schedulers")

    with patch(
        "stock_platform.api.lifecycle.validate_startup_settings",
        side_effect=lambda: call_order.append("settings"),
    ), patch(
        "stock_platform.api.lifecycle.verify_database_connection",
        new=AsyncMock(side_effect=database_check),
    ), patch(
        "stock_platform.api.lifecycle.broker_recovery_manager.recover",
        new=AsyncMock(side_effect=broker_recovery),
    ), patch.object(
        lifecycle,
        "_startup_strategy_runtime",
        new=AsyncMock(side_effect=strategy_runtime),
    ), patch.object(
        lifecycle,
        "_start_schedulers",
        new=AsyncMock(side_effect=start_schedulers),
    ):
        asyncio.run(lifecycle.startup())

    assert call_order == [
        "settings",
        "database",
        "broker",
        "strategy",
        "schedulers",
    ]


def test_shutdown_order(lifecycle: ApplicationLifecycle) -> None:
    lifecycle._started = True
    call_order: list[str] = []

    async def shutdown_schedulers() -> None:
        call_order.append("schedulers")

    async def clear_strategy() -> None:
        call_order.append("strategy")

    async def shutdown_realtime() -> None:
        call_order.append("realtime")

    with patch.object(
        lifecycle,
        "_shutdown_schedulers",
        new=AsyncMock(side_effect=shutdown_schedulers),
    ), patch(
        "stock_platform.api.lifecycle.dynamic_strategy_runtime_manager.clear",
        new=AsyncMock(side_effect=clear_strategy),
    ), patch.object(
        lifecycle,
        "_shutdown_realtime_services",
        new=AsyncMock(side_effect=shutdown_realtime),
    ):
        asyncio.run(lifecycle.shutdown())

    assert call_order == [
        "schedulers",
        "strategy",
        "realtime",
    ]
