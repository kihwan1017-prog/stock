"""STEP 8-5-5 — DynamicStrategyRuntimeManager (전역 슬롯 제거)."""

import asyncio

from stock_platform.strategy_deployment.runtime_manager import (
    DynamicStrategyRuntimeManager,
    RuntimeScopeRequiredError,
)
import pytest


def test_status_is_empty_initially() -> None:
    manager = DynamicStrategyRuntimeManager()
    status = manager.status()
    assert status["loaded"] is False
    assert status["runtime"] is None
    assert status["global_slot_removed"] is True


def test_clear_all_scopes() -> None:
    manager = DynamicStrategyRuntimeManager()
    asyncio.run(manager.clear())
    assert manager.status()["scoped_runtime_count"] == 0


def test_get_strategy_requires_scope() -> None:
    manager = DynamicStrategyRuntimeManager()
    with pytest.raises(RuntimeScopeRequiredError):
        manager.get_strategy()
