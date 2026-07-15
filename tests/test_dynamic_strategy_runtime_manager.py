import asyncio
from types import SimpleNamespace

from stock_platform.strategy_deployment.runtime_manager import (
    DynamicStrategyRuntimeManager,
)
from stock_platform.strategy_deployment.runtime_models import (
    LoadedStrategyRuntime,
)


def test_status_is_empty_initially() -> None:
    manager = DynamicStrategyRuntimeManager()

    status = manager.status()

    assert status["loaded"] is False
    assert status["runtime"] is None


def test_clear_removes_loaded_strategy() -> None:
    manager = DynamicStrategyRuntimeManager()
    manager._runtime = SimpleNamespace(
        deployment_id=1
    )
    manager._strategy = object()

    asyncio.run(manager.clear())

    assert manager.status()["loaded"] is False
