"""Multi-UBA LIVE Execution architecture — targeted tests.

실 broker API / Activation / LIVE / ARM / Worker START / backend reload 금지.
mock runner + mock adapter only.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from datetime import datetime, time as dt_time, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.api.v1 import realtime_execution as realtime_execution_api
from stock_platform.order.outbox_adapter_resolver import resolve_outbox_adapter
from stock_platform.order.outbox_dispatch_safety import (
    REASON_UBA_BROKER_MISMATCH,
    OutboxDispatchSafetyError,
    assert_live_outbox_dispatch_safety,
)
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.execution_runner_manager import (
    RealtimeExecutionRunnerManager,
    clone_safety_guard,
)
from stock_platform.realtime.execution_scope import (
    signal_matches_execution_scope,
)
from stock_platform.realtime.risk_integrated_order_executor import (
    RiskIntegratedRealtimeOrderExecutor,
)
from stock_platform.realtime.safety_guard import RealtimeOrderSafetyGuard
from stock_platform.realtime.safety_models import RealtimeOrderSafetyConfig
from stock_platform.realtime.signal_bus import RealtimeSignalBus
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)


UBA_UPBIT = 1380
UBA_KIWOOM = 1381


def _safety(*, live: bool = True, token: str = "T") -> RealtimeOrderSafetyGuard:
    return RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            max_order_amount=Decimal("100000"),
            max_daily_loss=Decimal("300000"),
            max_open_positions=50,
            duplicate_order_window_seconds=0,
            symbol_cooldown_seconds=0,
            max_orders_per_minute=100,
            trading_start_time=dt_time(0, 0),
            trading_end_time=dt_time(23, 59),
            enforce_market_hours_for_krx=False,
            live_trading_enabled=live,
            live_unlock_token=token,
        )
    )


def _paper_cfg() -> RealtimeExecutionConfig:
    return RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.PAPER,
        account_id=1,
        order_amount=Decimal("100000"),
    )


def _live_cfg(uba: int, broker: str) -> RealtimeExecutionConfig:
    return RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.LIVE,
        account_id=1,
        order_amount=Decimal("100000"),
        auto_fill=False,
        user_broker_account_id=int(uba),
        broker_code=str(broker).upper(),
    )


def _live_signal(
    *,
    uba: int,
    broker: str,
    symbol: str,
    strategy_id: int = 1,
) -> RealtimeSignal:
    broker_u = str(broker).upper()
    exchange = "UPBIT" if broker_u == "UPBIT" else "KRX"
    return RealtimeSignal(
        exchange_code=exchange,
        symbol=symbol,
        action=RealtimeSignalAction.BUY,
        signal_price=Decimal("1000"),
        short_average=None,
        long_average=None,
        change_rate=None,
        reason_code="TEST",
        generated_at=datetime.now(timezone.utc),
        scope_key=f"{broker_u}:{uba}:{strategy_id}:{symbol}",
        account_kind="USER_BROKER",
        account_id=int(uba),
        user_broker_account_id=int(uba),
        broker_code=broker_u,
        strategy_id=int(strategy_id),
        market_type="CRYPTO" if broker_u == "UPBIT" else "STOCK",
    )


def _skip_result(signal: RealtimeSignal, reason: str = "TEST_SKIP"):
    return SimpleNamespace(
        exchange_code=signal.exchange_code,
        symbol=signal.symbol,
        signal_action=signal.action.value,
        execution_mode="LIVE",
        order_id=None,
        trade_id=None,
        order_status="SKIPPED",
        quantity=Decimal("0"),
        order_price=signal.signal_price,
        reason_code=reason,
        executed_at=datetime.now(timezone.utc),
    )


def _isolated_manager() -> RealtimeExecutionRunnerManager:
    return RealtimeExecutionRunnerManager(
        signal_bus=RealtimeSignalBus(),
        safety_guard_template=_safety(live=False, token=""),
        paper_config=_paper_cfg(),
    )


def _bind_live(manager: RealtimeExecutionRunnerManager, uba: int, broker: str):
    return manager.get_or_create_live(
        user_broker_account_id=uba,
        broker_code=broker,
        config=_live_cfg(uba, broker),
        safety_guard=_safety(),
    )


async def _wait_count(runner, attr: str, expected: int, timeout: float = 1.5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if int(getattr(runner, attr)) >= expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"{attr} expected >={expected}, got {getattr(runner, attr)}"
    )


@pytest.mark.asyncio
async def test_a_simultaneous_upbit_and_kiwoom_runners_start() -> None:
    """A. 1380 RUNNING + 1381 START → 둘 다 RUNNING."""

    manager = _isolated_manager()
    upbit = _bind_live(manager, UBA_UPBIT, "UPBIT")
    kiwoom = _bind_live(manager, UBA_KIWOOM, "KIWOOM")
    upbit._execute_signal = lambda signal: _skip_result(signal)
    kiwoom._execute_signal = lambda signal: _skip_result(signal)

    await manager.start_scope(UBA_UPBIT, "UPBIT")
    assert upbit.status()["running"] is True
    await manager.start_scope(UBA_KIWOOM, "KIWOOM")
    assert upbit.status()["running"] is True
    assert kiwoom.status()["running"] is True
    assert manager.signal_bus.subscriber_count == 2

    await manager.stop_all()


@pytest.mark.asyncio
async def test_b_stop_kiwoom_keeps_upbit_running() -> None:
    """B. 1381 STOP → 1380 RUNNING 유지, subscriber만 1381 제거."""

    manager = _isolated_manager()
    upbit = _bind_live(manager, UBA_UPBIT, "UPBIT")
    kiwoom = _bind_live(manager, UBA_KIWOOM, "KIWOOM")
    upbit._execute_signal = lambda signal: _skip_result(signal)
    kiwoom._execute_signal = lambda signal: _skip_result(signal)
    await manager.start_scope(UBA_UPBIT, "UPBIT")
    await manager.start_scope(UBA_KIWOOM, "KIWOOM")
    await asyncio.sleep(0)
    assert manager.signal_bus.subscriber_count == 2

    await manager.stop_scope(UBA_KIWOOM, "KIWOOM")
    await asyncio.sleep(0.05)
    assert upbit.status()["running"] is True
    assert kiwoom.status()["running"] is False
    assert manager.signal_bus.subscriber_count == 1

    await manager.stop_all()


@pytest.mark.asyncio
async def test_c_stop_upbit_keeps_kiwoom_running() -> None:
    """C. 1380 STOP → 1381 RUNNING 유지."""

    manager = _isolated_manager()
    upbit = _bind_live(manager, UBA_UPBIT, "UPBIT")
    kiwoom = _bind_live(manager, UBA_KIWOOM, "KIWOOM")
    upbit._execute_signal = lambda signal: _skip_result(signal)
    kiwoom._execute_signal = lambda signal: _skip_result(signal)
    await manager.start_scope(UBA_UPBIT, "UPBIT")
    await manager.start_scope(UBA_KIWOOM, "KIWOOM")

    await manager.stop_scope(UBA_UPBIT, "UPBIT")
    await asyncio.sleep(0.05)
    assert kiwoom.status()["running"] is True
    assert upbit.status()["running"] is False
    assert manager.signal_bus.subscriber_count == 1

    await manager.stop_all()


@pytest.mark.asyncio
async def test_d_each_runner_processes_only_own_signal() -> None:
    """D. 동시 publish → 각 Runner 자기 signal 1개만 processed."""

    manager = _isolated_manager()
    upbit = _bind_live(manager, UBA_UPBIT, "UPBIT")
    kiwoom = _bind_live(manager, UBA_KIWOOM, "KIWOOM")
    upbit._execute_signal = lambda signal: _skip_result(signal, "OWN_UPBIT")
    kiwoom._execute_signal = lambda signal: _skip_result(signal, "OWN_KIWOOM")
    await manager.start_scope(UBA_UPBIT, "UPBIT")
    await manager.start_scope(UBA_KIWOOM, "KIWOOM")
    await asyncio.sleep(0)

    await asyncio.gather(
        manager.signal_bus.publish(
            _live_signal(uba=UBA_UPBIT, broker="UPBIT", symbol="KRW-XRP")
        ),
        manager.signal_bus.publish(
            _live_signal(uba=UBA_KIWOOM, broker="KIWOOM", symbol="005930")
        ),
    )
    await _wait_count(upbit, "_processed_count", 1)
    await _wait_count(kiwoom, "_processed_count", 1)
    assert upbit._processed_count == 1
    assert kiwoom._processed_count == 1

    await manager.stop_all()


@pytest.mark.asyncio
async def test_e_cross_uba_signal_does_not_execute() -> None:
    """E. cross UBA signal → 상대 Runner processed 0, broker CREATE 0."""

    manager = _isolated_manager()
    creates: list[str] = []
    upbit = _bind_live(manager, UBA_UPBIT, "UPBIT")
    kiwoom = _bind_live(manager, UBA_KIWOOM, "KIWOOM")

    def upbit_exec(signal):
        creates.append("UPBIT")
        return _skip_result(signal)

    def kiwoom_exec(signal):
        creates.append("KIWOOM")
        return _skip_result(signal)

    upbit._execute_signal = upbit_exec
    kiwoom._execute_signal = kiwoom_exec
    await manager.start_scope(UBA_UPBIT, "UPBIT")
    await manager.start_scope(UBA_KIWOOM, "KIWOOM")
    await asyncio.sleep(0)

    # 1380 Runner에게 KIWOOM/1381 신호
    await manager.signal_bus.publish(
        _live_signal(uba=UBA_KIWOOM, broker="KIWOOM", symbol="005930")
    )
    await asyncio.sleep(0.15)
    assert upbit._processed_count == 0
    assert "UPBIT" not in creates
    # 1381은 자기 신호이므로 1
    await _wait_count(kiwoom, "_processed_count", 1)
    await manager.stop_all()


@pytest.mark.asyncio
async def test_failure_isolation_kiwoom_exception_keeps_upbit() -> None:
    manager = _isolated_manager()
    upbit = _bind_live(manager, UBA_UPBIT, "UPBIT")
    kiwoom = _bind_live(manager, UBA_KIWOOM, "KIWOOM")
    upbit._execute_signal = lambda signal: _skip_result(signal)

    def boom(_signal):
        raise RuntimeError("KIWOOM_TEST_FAIL")

    kiwoom._execute_signal = boom
    await manager.start_scope(UBA_UPBIT, "UPBIT")
    await manager.start_scope(UBA_KIWOOM, "KIWOOM")
    await asyncio.sleep(0)

    await manager.signal_bus.publish(
        _live_signal(uba=UBA_KIWOOM, broker="KIWOOM", symbol="005930")
    )
    await _wait_count(kiwoom, "_failed_count", 1)
    assert upbit.status()["running"] is True
    assert manager.signal_bus.subscriber_count == 2

    before = upbit._processed_count
    await manager.signal_bus.publish(
        _live_signal(uba=UBA_UPBIT, broker="UPBIT", symbol="KRW-XRP")
    )
    await _wait_count(upbit, "_processed_count", before + 1)
    assert upbit.status()["running"] is True
    await manager.stop_all()


@pytest.mark.asyncio
async def test_failure_isolation_upbit_exception_keeps_kiwoom() -> None:
    manager = _isolated_manager()
    upbit = _bind_live(manager, UBA_UPBIT, "UPBIT")
    kiwoom = _bind_live(manager, UBA_KIWOOM, "KIWOOM")
    kiwoom._execute_signal = lambda signal: _skip_result(signal)
    upbit._execute_signal = lambda _s: (_ for _ in ()).throw(RuntimeError("UPBIT_FAIL"))
    await manager.start_scope(UBA_UPBIT, "UPBIT")
    await manager.start_scope(UBA_KIWOOM, "KIWOOM")
    await asyncio.sleep(0)
    await manager.signal_bus.publish(
        _live_signal(uba=UBA_UPBIT, broker="UPBIT", symbol="KRW-XRP")
    )
    await _wait_count(upbit, "_failed_count", 1)
    assert kiwoom.status()["running"] is True
    await manager.signal_bus.publish(
        _live_signal(uba=UBA_KIWOOM, broker="KIWOOM", symbol="005930")
    )
    await _wait_count(kiwoom, "_processed_count", 1)
    await manager.stop_all()


def test_cross_broker_executor_skip_when_config_is_upbit() -> None:
    executor = RiskIntegratedRealtimeOrderExecutor.__new__(
        RiskIntegratedRealtimeOrderExecutor
    )
    executor._session = MagicMock()
    executor._execution_config = _live_cfg(UBA_UPBIT, "UPBIT")
    executor._safety_guard = _safety()
    skipped = []

    def fake_skip(signal, reason):
        skipped.append(reason)
        return _skip_result(signal, reason)

    executor._skipped = fake_skip  # type: ignore[method-assign]
    result = executor.execute(
        _live_signal(uba=UBA_UPBIT, broker="KIWOOM", symbol="005930")
    )
    assert "CROSS_BROKER_SIGNAL" in skipped
    assert result.reason_code == "CROSS_BROKER_SIGNAL"


def test_cross_uba_executor_skip() -> None:
    executor = RiskIntegratedRealtimeOrderExecutor.__new__(
        RiskIntegratedRealtimeOrderExecutor
    )
    executor._session = MagicMock()
    executor._execution_config = _live_cfg(UBA_UPBIT, "UPBIT")
    executor._safety_guard = _safety()
    skipped = []

    def fake_skip(signal, reason):
        skipped.append(reason)
        return _skip_result(signal, reason)

    executor._skipped = fake_skip  # type: ignore[method-assign]
    executor.execute(
        _live_signal(uba=UBA_KIWOOM, broker="UPBIT", symbol="KRW-XRP")
    )
    assert "CROSS_UBA_SIGNAL" in skipped


def test_kiwoom_signal_matches_kiwoom_runner_scope() -> None:
    cfg = _live_cfg(UBA_KIWOOM, "KIWOOM")
    own = _live_signal(uba=UBA_KIWOOM, broker="KIWOOM", symbol="005930")
    other = _live_signal(uba=UBA_UPBIT, broker="UPBIT", symbol="KRW-XRP")
    assert signal_matches_execution_scope(own, cfg) is True
    assert signal_matches_execution_scope(other, cfg) is False


def test_status_lists_independent_runners() -> None:
    manager = _isolated_manager()
    _bind_live(manager, UBA_UPBIT, "UPBIT")
    _bind_live(manager, UBA_KIWOOM, "KIWOOM")
    rows = manager.runners_status()
    by_uba = {row["uba"]: row for row in rows if row["uba"]}
    assert by_uba[UBA_UPBIT]["broker"] == "UPBIT"
    assert by_uba[UBA_KIWOOM]["broker"] == "KIWOOM"
    assert by_uba[UBA_UPBIT]["running"] is False
    compat = manager.compatibility_status()
    assert "runners" in compat
    assert len(compat["runners"]) >= 2


def test_scoped_start_source_does_not_stop_other_runners() -> None:
    source = inspect.getsource(realtime_execution_api._start_live_for_uba)
    assert "stop_all" not in source
    assert "await realtime_execution_runner.stop()" not in source
    assert "await existing.stop()" not in source


@pytest.mark.asyncio
async def test_unscoped_stop_refuses_when_two_live_running() -> None:
    manager = _isolated_manager()
    upbit = _bind_live(manager, UBA_UPBIT, "UPBIT")
    kiwoom = _bind_live(manager, UBA_KIWOOM, "KIWOOM")
    upbit._execute_signal = lambda s: _skip_result(s)
    kiwoom._execute_signal = lambda s: _skip_result(s)
    await manager.start_scope(UBA_UPBIT, "UPBIT")
    await manager.start_scope(UBA_KIWOOM, "KIWOOM")
    with patch.object(
        realtime_execution_api,
        "realtime_execution_runner_manager",
        manager,
    ), patch.object(
        realtime_execution_api,
        "realtime_execution_runner",
        MagicMock(),
    ):
        with pytest.raises(realtime_execution_api.HTTPException) as exc:
            await realtime_execution_api.stop_realtime_execution()
        assert exc.value.status_code == 409
        assert exc.value.detail == realtime_execution_api.MULTI_SCOPE_STOP_REQUIRES_UBA
    assert upbit.status()["running"] is True
    assert kiwoom.status()["running"] is True
    await manager.stop_all()


@pytest.mark.asyncio
async def test_asyncio_to_thread_does_not_block_event_loop() -> None:
    manager = _isolated_manager()
    upbit = _bind_live(manager, UBA_UPBIT, "UPBIT")

    def slow(signal):
        time.sleep(0.25)
        return _skip_result(signal)

    upbit._execute_signal = slow
    await manager.start_scope(UBA_UPBIT, "UPBIT")
    await asyncio.sleep(0)
    await manager.signal_bus.publish(
        _live_signal(uba=UBA_UPBIT, broker="UPBIT", symbol="KRW-XRP")
    )
    t0 = time.perf_counter()
    await asyncio.sleep(0.05)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.2
    await _wait_count(upbit, "_processed_count", 1, timeout=2.0)
    await manager.stop_all()


def test_outbox_live_upbit_routes_to_upbit_factory() -> None:
    created: list[str] = []

    def fake_create(environment, broker_code, **kwargs):
        created.append(str(broker_code).upper())
        return MagicMock()

    with patch(
        "stock_platform.order.outbox_adapter_resolver.BrokerAdapterFactory.create",
        side_effect=fake_create,
    ):
        resolve_outbox_adapter(
            {
                "environment": "LIVE",
                "broker_code": "UPBIT",
                "user_broker_account_id": UBA_UPBIT,
            },
            session=MagicMock(),
        )
    assert created == ["UPBIT"]


def test_outbox_live_kiwoom_routes_to_kiwoom_factory() -> None:
    created: list[str] = []

    def fake_create(environment, broker_code, **kwargs):
        created.append(str(broker_code).upper())
        return MagicMock()

    with patch(
        "stock_platform.order.outbox_adapter_resolver.BrokerAdapterFactory.create",
        side_effect=fake_create,
    ):
        resolve_outbox_adapter(
            {
                "environment": "LIVE",
                "broker_code": "KIWOOM",
                "user_broker_account_id": UBA_KIWOOM,
            },
            session=MagicMock(),
        )
    assert created == ["KIWOOM"]


def test_outbox_dispatch_rejects_cross_broker_uba() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=UBA_UPBIT,
        broker_code="UPBIT",
        is_active=True,
        user_id=61,
        live_order_enabled=True,
        live_armed=True,
    )
    session.get.return_value = uba
    with patch(
        "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
        return_value=SimpleNamespace(code="UPBIT_FLAGS_OK", allowed=True),
    ), patch(
        "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
    ):
        with pytest.raises(OutboxDispatchSafetyError) as exc:
            assert_live_outbox_dispatch_safety(
                session,
                {
                    "environment": "LIVE",
                    "broker_code": "KIWOOM",
                    "user_broker_account_id": UBA_UPBIT,
                },
            )
    assert exc.value.reason_code == REASON_UBA_BROKER_MISMATCH


def test_clone_safety_guard_is_independent() -> None:
    template = _safety(live=False, token="")
    cloned = clone_safety_guard(
        template,
        live_trading_enabled=True,
        live_unlock_token="X",
    )
    cloned.add_realized_profit_loss(Decimal("-100"))
    assert template.daily_realized_loss == Decimal("0")
    assert cloned.daily_realized_loss > Decimal("0")


def test_kiwoom_gate_does_not_call_upbit_pause() -> None:
    from stock_platform.realtime.kiwoom_runtime_run_gates import (
        evaluate_kiwoom_runtime_run_gates,
    )

    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=UBA_KIWOOM,
        broker_code="KIWOOM",
        is_active=True,
        deleted_at=None,
        connection_status="CONNECTED",
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=None,
    )
    session.get.return_value = uba
    with patch(
        "stock_platform.trading.upbit_24x7_control.pause_upbit_runtimes_sync"
    ) as pause, patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates.assert_uba_connection_ready"
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates._credential_verified",
        return_value=(True, "VERIFIED"),
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates.assert_recovery_ready",
        return_value={"trading_paused": False, "recovery_status": "SUCCESS"},
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates.assert_risk_account_not_paused",
        return_value={"ok": True},
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates._kill_active_kiwoom",
        return_value=False,
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates._activation_active_kiwoom",
        return_value={"ok": False},
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates.live_outbox_queue_block_reason",
        return_value=None,
    ):
        result = evaluate_kiwoom_runtime_run_gates(
            session,
            user_broker_account_id=UBA_KIWOOM,
        )
    pause.assert_not_called()
    assert result["ok"] is False
    assert result["runtime_paused"] is False
    assert "LIVE_OFF" in result["blockers"] or "ACTIVATION_INACTIVE" in result["blockers"]
