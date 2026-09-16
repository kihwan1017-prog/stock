"""STEP 8-5-5 — Scope Runtime Registry tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from stock_platform.strategy_deployment.runtime_manager import (
    DynamicStrategyRuntimeManager,
    RuntimeScopeRequiredError,
    ScopedRuntimeEntry,
)
from stock_platform.strategy_deployment.runtime_models import (
    LoadedStrategyRuntime,
)
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
    StrategyRuntimeScopeError,
)


def _scope(
    *,
    user_id: int = 1,
    account_id: int = 10,
    strategy_id: int = 100,
    kind: AccountKind = AccountKind.PAPER,
    broker: str = "PAPER",
    version: str = "v1",
    market_type: str = "STOCK",
) -> StrategyRuntimeScope:
    return StrategyRuntimeScope(
        user_id=user_id,
        account_kind=kind,
        account_id=account_id,
        strategy_id=strategy_id,
        strategy_version=version,
        market_type=market_type,
        broker_code=broker,
        strategy_code="MA",
        market_code="KRX" if broker == "PAPER" else broker,
    )


def _entry(scope: StrategyRuntimeScope) -> ScopedRuntimeEntry:
    runtime = LoadedStrategyRuntime(
        deployment_id=1,
        strategy_code="MA",
        market_code=scope.market_code,
        symbol="005930",
        parameter_payload={},
        loaded_at=datetime.now(timezone.utc),
        user_id=scope.user_id,
        account_id=scope.paper_account_id,
        user_broker_account_id=scope.user_broker_account_id,
        strategy_id=scope.strategy_id,
        strategy_version=scope.strategy_version,
        market_type=scope.market_type,
        scope_key=scope.scope_key,
        broker_code=scope.broker_code,
        account_kind=scope.account_kind.value,
    )
    return ScopedRuntimeEntry(
        scope=scope,
        runtime=runtime,
        strategy=object(),
        status=RuntimeLifecycleStatus.RUNNING,
    )


def test_scope_requires_account_and_user() -> None:
    with pytest.raises(StrategyRuntimeScopeError):
        StrategyRuntimeScope(
            user_id=0,
            account_kind=AccountKind.PAPER,
            account_id=1,
            strategy_id=1,
            strategy_version="v1",
            market_type="STOCK",
            broker_code="PAPER",
        )


def test_live_uba_cannot_use_paper_broker() -> None:
    with pytest.raises(StrategyRuntimeScopeError):
        StrategyRuntimeScope(
            user_id=1,
            account_kind=AccountKind.USER_BROKER,
            account_id=9,
            strategy_id=1,
            strategy_version="v1",
            market_type="CRYPTO",
            broker_code="PAPER",
        )


def test_scope_key_stable_and_separated() -> None:
    a = _scope(user_id=1, account_id=10)
    b = _scope(user_id=1, account_id=11)
    c = _scope(user_id=2, account_id=10)
    d = _scope(
        user_id=1,
        account_id=10,
        kind=AccountKind.USER_BROKER,
        broker="UPBIT",
        market_type="CRYPTO",
    )
    assert a.scope_key == _scope(user_id=1, account_id=10).scope_key
    assert a.scope_key != b.scope_key
    assert a.scope_key != c.scope_key
    assert a.scope_key != d.scope_key
    assert "uba:" in d.scope_key
    assert "paper:" in a.scope_key


def test_get_without_scope_fails() -> None:
    manager = DynamicStrategyRuntimeManager()
    with pytest.raises(RuntimeScopeRequiredError):
        manager.get_strategy()
    with pytest.raises(RuntimeScopeRequiredError):
        manager.get_runtime()


def test_registry_isolation_and_pause() -> None:
    manager = DynamicStrategyRuntimeManager()
    s1 = _scope(user_id=1, account_id=10, strategy_id=100)
    s2 = _scope(user_id=1, account_id=11, strategy_id=100)
    asyncio.run(manager.put_entry(_entry(s1)))
    asyncio.run(manager.put_entry(_entry(s2)))

    assert manager.get_strategy(scope_key=s1.scope_key) is not None
    assert len(manager.list_entries(user_id=1)) == 2
    assert len(manager.list_entries(paper_account_id=10)) == 1

    paused = asyncio.run(
        manager.pause_account_runtimes(
            paper_account_id=10, reason="recovery_running"
        )
    )
    assert s1.scope_key in paused
    assert manager.get_entry(s1.scope_key).status == (
        RuntimeLifecycleStatus.PAUSED
    )
    assert manager.get_entry(s2.scope_key).status == (
        RuntimeLifecycleStatus.RUNNING
    )


def test_status_has_no_global_runtime_slot() -> None:
    manager = DynamicStrategyRuntimeManager()
    status = manager.status()
    assert status["loaded"] is False
    assert status["runtime"] is None
    assert status["global_slot_removed"] is True
    assert status["scoped_runtime_count"] == 0


def test_clear_removes_scoped_only() -> None:
    manager = DynamicStrategyRuntimeManager()
    scope = _scope()
    asyncio.run(manager.put_entry(_entry(scope)))
    asyncio.run(manager.clear(scope_key=scope.scope_key))
    assert manager.get_entry(scope.scope_key) is None


def test_shutdown_all() -> None:
    manager = DynamicStrategyRuntimeManager()
    asyncio.run(manager.put_entry(_entry(_scope())))
    result = asyncio.run(manager.shutdown_all())
    assert result["stopped"] == 1
    assert manager.status()["scoped_runtime_count"] == 0


def test_no_global_runtime_attributes() -> None:
    manager = DynamicStrategyRuntimeManager()
    assert not hasattr(manager, "_runtime")
    assert not hasattr(manager, "_strategy")
