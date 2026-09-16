"""UPBIT KRW-SOL controlled LIVE activation PRECHECK — unit/fixture only.

production DB mutation 없음. broker CREATE/CANCEL/AMEND 없음.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    COMPILER_SUPPORTED_TIMEFRAMES,
)
from stock_platform.broker.upbit.rules import (
    UPBIT_MIN_NOTIONAL_KRW,
    evaluate_upbit_min_notional,
)
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.outbox_repository import OrderOutboxRepository
from stock_platform.realtime.consumer_registry import ScopeConsumerRegistry
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.execution_scope import signal_matches_execution_scope
from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.market_data_hub import RealtimeMarketDataHub
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.models import MarketEventType, RealtimeQuote
from stock_platform.realtime.runtime_bridge import _config_from_entry, _symbols_for_entry
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeSignal,
    RealtimeSignalAction,
    RealtimeStrategyConfig,
)
from stock_platform.realtime.upbit_quote_feed_restore import collect_upbit_symbols_from_hub
from stock_platform.risk_engine.exit_risk import is_order_outstanding_for_sell
from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskDecisionLevel,
    RiskOrderRequest,
    RiskOrderSide,
    RiskPolicy,
)
from stock_platform.risk_engine.rules import MaximumOpenPositionsRule
from stock_platform.strategy_deployment.runtime_manager import (
    DynamicStrategyRuntimeManager,
    ScopedRuntimeEntry,
)
from stock_platform.strategy_deployment.runtime_models import LoadedStrategyRuntime
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)


def _scope(*, strategy_id: int, symbol_unused: str = "") -> StrategyRuntimeScope:
    return StrategyRuntimeScope(
        user_id=61,
        account_kind=AccountKind.USER_BROKER,
        account_id=1380,
        strategy_id=strategy_id,
        strategy_version="1",
        market_type="CRYPTO",
        broker_code="UPBIT",
    )


def _event(symbol: str, price: str, *, now: datetime | None = None) -> RealtimeMarketEvent:
    ts = now or datetime.now(timezone.utc)
    return RealtimeMarketEvent(
        broker_code="UPBIT",
        market_type="CRYPTO",
        symbol=symbol,
        event_type="TRADE",
        event_time=ts,
        received_at=ts,
        exchange_code="UPBIT",
        price=Decimal(price),
        source_code="UPBIT_WEBSOCKET",
    )


def test_compiler_timeframe_is_daily_only() -> None:
    assert COMPILER_SUPPORTED_TIMEFRAMES == frozenset({"1D"})


def test_live_ma_evaluator_tick_path_still_uses_raw_prices() -> None:
    src = inspect.getsource(MovingAverageStrategyEvaluator.evaluate)
    assert "state.prices.append(event.price)" in src
    assert "uses_daily_bars" in src
    assert "MA_GOLDEN_CROSS" in src
    assert "MA_DEAD_CROSS" in src
    assert "STOP_LOSS" in src
    assert "TAKE_PROFIT" in src

    ev = MovingAverageStrategyEvaluator(
        _scope(strategy_id=17580),
        RealtimeStrategyConfig(short_window=5, long_window=20, cooldown_seconds=0),
    )
    state = ev.get_state("KRW-SOL")
    assert state.prices.maxlen == 21
    empty = RealtimePositionState(quantity=Decimal("0"), average_entry_price=None)
    now = datetime.now(timezone.utc)
    for i in range(20):
        signal = ev.evaluate(
            _event("KRW-SOL", "100", now=now + timedelta(milliseconds=i)),
            position=empty,
        )
        assert signal is None
    assert ev.warmup_status("KRW-SOL").value == "WARMING_UP"
    assert len(ev.get_state("KRW-SOL").prices) == 20


def test_buy_only_when_qty_zero_and_sell_paths() -> None:
    ev = MovingAverageStrategyEvaluator(
        _scope(strategy_id=17580),
        RealtimeStrategyConfig(
            short_window=2,
            long_window=3,
            cooldown_seconds=0,
            stop_loss_ratio=Decimal("0.03"),
            take_profit_ratio=Decimal("0.06"),
        ),
    )
    empty = RealtimePositionState(quantity=Decimal("0"), average_entry_price=None)
    now = datetime.now(timezone.utc)
    prices = ["10", "9", "8", "11"]
    last = None
    for i, px in enumerate(prices):
        last = ev.evaluate(
            _event("KRW-SOL", px, now=now + timedelta(milliseconds=i)),
            position=empty,
        )
    assert last is not None
    assert last.signal_type == "BUY"
    assert last.reason_code == "MA_GOLDEN_CROSS"

    held = RealtimePositionState(
        quantity=Decimal("1"), average_entry_price=Decimal("100")
    )
    sl = ev.evaluate(_event("KRW-SOL", "96", now=now + timedelta(seconds=1)), position=held)
    assert sl is not None
    assert sl.reason_code == "STOP_LOSS"

    ev.reset()
    tp = ev.evaluate(_event("KRW-SOL", "107", now=now + timedelta(seconds=2)), position=held)
    assert tp is not None
    assert tp.reason_code == "TAKE_PROFIT"


def test_runtime_bridge_reads_timeframe_field() -> None:
    src = inspect.getsource(_config_from_entry)
    assert "timeframe" in src
    entry = SimpleNamespace(
        runtime=SimpleNamespace(
            symbol="KRW-SOL",
            parameter_payload={
                "symbol": "KRW-SOL",
                "symbols": ["KRW-SOL"],
                "timeframe": "1D",
                "short_window": 5,
                "long_window": 20,
                "stop_loss": "0.03",
                "take_profit": "0.06",
                "cooldown_seconds": 30,
            },
        )
    )
    assert _symbols_for_entry(entry) == ["KRW-SOL"]
    cfg = _config_from_entry(entry)
    assert cfg.short_window == 5
    assert cfg.long_window == 20
    assert cfg.stop_loss_ratio == Decimal("0.03")
    assert cfg.take_profit_ratio == Decimal("0.06")
    assert cfg.cooldown_seconds == 30
    assert cfg.timeframe == "1D"
    assert cfg.uses_daily_bars()


def test_hub_xrp_and_sol_subscriptions_dispatch_isolation() -> None:
    hub = RealtimeMarketDataHub()
    xrp = _scope(strategy_id=17483)
    sol = _scope(strategy_id=17580)
    hub.register_consumer(xrp, ["KRW-XRP"], runtime_status=RuntimeLifecycleStatus.RUNNING)
    hub.register_consumer(sol, ["KRW-SOL"], runtime_status=RuntimeLifecycleStatus.RUNNING)
    keys = {row["symbol"]: row for row in hub.registry.list_subscriptions()}
    assert "KRW-XRP" in keys
    assert "KRW-SOL" in keys
    now = datetime.now(timezone.utc)
    hub.ingest_quote_sync(
        RealtimeQuote(
            exchange_code="UPBIT",
            symbol="KRW-SOL",
            event_type=MarketEventType.TRADE,
            trade_price=Decimal("200000"),
            opening_price=None,
            high_price=None,
            low_price=None,
            previous_close_price=None,
            change_price=None,
            change_rate=None,
            accumulated_volume=None,
            trade_volume=None,
            event_time=now,
            received_at=now,
            source_code="UPBIT_WEBSOCKET",
        )
    )
    consumers = {c["scope_key"]: c for c in hub.registry.list_consumers()}
    assert consumers[sol.scope_key]["event_count"] == 1
    assert consumers[xrp.scope_key]["event_count"] == 0


def test_cross_strategy_signal_rejected_by_subscription_key() -> None:
    registry = ScopeConsumerRegistry()
    xrp = _scope(strategy_id=17483)
    sol = _scope(strategy_id=17580)
    registry.register_consumer(xrp, ["KRW-XRP"], runtime_status=RuntimeLifecycleStatus.RUNNING)
    registry.register_consumer(sol, ["KRW-SOL"], runtime_status=RuntimeLifecycleStatus.RUNNING)
    now = datetime.now(timezone.utc)
    signals = registry.dispatch(_event("KRW-XRP", "3000", now=now))
    consumers = {c["scope_key"]: c for c in registry.list_consumers()}
    assert consumers[xrp.scope_key]["event_count"] == 1
    assert consumers[sol.scope_key]["event_count"] == 0
    assert all(s.strategy_id == 17483 for s in signals)


def test_same_uba_runner_accepts_multi_strategy_rejects_cross_uba() -> None:
    cfg = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.LIVE,
        account_id=1,
        user_broker_account_id=1380,
        broker_code="UPBIT",
    )
    now = datetime.now(timezone.utc)

    def _sig(*, strategy_id: int, symbol: str, uba: int, broker: str) -> RealtimeSignal:
        return RealtimeSignal(
            exchange_code="UPBIT" if broker == "UPBIT" else "KRX",
            symbol=symbol,
            action=RealtimeSignalAction.BUY,
            signal_price=Decimal("10000"),
            short_average=None,
            long_average=None,
            change_rate=None,
            reason_code="TEST",
            generated_at=now,
            strategy_id=strategy_id,
            broker_code=broker,
            account_kind="USER_BROKER",
            account_id=uba,
            user_broker_account_id=uba,
            user_id=61,
        )

    assert signal_matches_execution_scope(
        _sig(strategy_id=17580, symbol="KRW-SOL", uba=1380, broker="UPBIT"), cfg
    )
    assert signal_matches_execution_scope(
        _sig(strategy_id=17483, symbol="KRW-XRP", uba=1380, broker="UPBIT"), cfg
    )
    assert not signal_matches_execution_scope(
        _sig(strategy_id=17579, symbol="005930", uba=1381, broker="KIWOOM"), cfg
    )


def test_runtime_manager_sol_start_does_not_replace_xrp() -> None:
    import asyncio

    manager = DynamicStrategyRuntimeManager()
    xrp_scope = _scope(strategy_id=17483)
    sol_scope = _scope(strategy_id=17580)
    now = datetime.now(timezone.utc)

    def _entry(scope: StrategyRuntimeScope, symbol: str) -> ScopedRuntimeEntry:
        runtime = LoadedStrategyRuntime(
            deployment_id=scope.strategy_id,
            strategy_code=f"SID_{scope.strategy_id}",
            market_code="UPBIT",
            symbol=symbol,
            parameter_payload={"symbol": symbol, "symbols": [symbol]},
            loaded_at=now,
            user_id=61,
            user_broker_account_id=1380,
            strategy_id=scope.strategy_id,
            strategy_version=scope.strategy_version,
            market_type=scope.market_type,
            broker_code=scope.broker_code,
        )
        return ScopedRuntimeEntry(
            scope=scope,
            runtime=runtime,
            strategy=object(),
            status=RuntimeLifecycleStatus.CREATED,
        )

    async def _run() -> None:
        await manager.put_entry(_entry(xrp_scope, "KRW-XRP"), replace=False)
        await manager.put_entry(_entry(sol_scope, "KRW-SOL"), replace=False)
        keys = {e.scope.scope_key for e in manager._runtimes.values()}
        assert xrp_scope.scope_key in keys
        assert sol_scope.scope_key in keys
        assert xrp_scope.scope_key != sol_scope.scope_key

    asyncio.run(_run())


def test_worker_claim_excludes_failed_ambiguous_absent() -> None:
    src = inspect.getsource(OrderOutboxRepository.claim_batch)
    assert "OutboxStatus.PENDING.value" in src
    assert "OutboxStatus.RETRY.value" in src
    assert "FAILED" not in src
    assert "AMBIGUOUS" not in src
    assert "CONFIRMED_ABSENT" not in src
    assert {OutboxStatus.PENDING.value, OutboxStatus.RETRY.value} <= {
        "PENDING",
        "RETRY",
    }


def test_position_cap_allows_sol_entry_then_blocks_seventh() -> None:
    now = datetime.now(timezone.utc)
    policy = RiskPolicy(max_open_positions=6)
    account = RiskAccountState(
        cash_balance=Decimal("164000"),
        total_asset_value=Decimal("5000000"),
        invested_amount=Decimal("4800000"),
        daily_realized_profit_loss=Decimal("0"),
        daily_unrealized_profit_loss=Decimal("0"),
        open_position_count=5,
        symbol_position_quantity=Decimal("0"),
    )
    buy_sol = RiskOrderRequest(
        exchange_code="UPBIT",
        symbol="KRW-SOL",
        side=RiskOrderSide.BUY,
        quantity=Decimal("0.04"),
        price=Decimal("250000"),
        requested_at=now,
        user_broker_account_id=1380,
        environment="LIVE",
    )
    assert MaximumOpenPositionsRule().evaluate(
        order=buy_sol, account=account, policy=policy
    ).level == RiskDecisionLevel.PASS

    account_full = RiskAccountState(
        cash_balance=Decimal("154000"),
        total_asset_value=Decimal("5010000"),
        invested_amount=Decimal("4810000"),
        daily_realized_profit_loss=Decimal("0"),
        daily_unrealized_profit_loss=Decimal("0"),
        open_position_count=6,
        symbol_position_quantity=Decimal("0"),
    )
    buy_other = RiskOrderRequest(
        exchange_code="UPBIT",
        symbol="KRW-GRVT",
        side=RiskOrderSide.BUY,
        quantity=Decimal("10"),
        price=Decimal("400"),
        requested_at=now,
        user_broker_account_id=1380,
        environment="LIVE",
    )
    assert MaximumOpenPositionsRule().evaluate(
        order=buy_other, account=account_full, policy=policy
    ).level == RiskDecisionLevel.BLOCK

    sell = RiskOrderRequest(
        exchange_code="UPBIT",
        symbol="KRW-SOL",
        side=RiskOrderSide.SELL,
        quantity=Decimal("0.04"),
        price=Decimal("250000"),
        requested_at=now,
        user_broker_account_id=1380,
        environment="LIVE",
    )
    account_held = RiskAccountState(
        cash_balance=Decimal("154000"),
        total_asset_value=Decimal("5010000"),
        invested_amount=Decimal("4810000"),
        daily_realized_profit_loss=Decimal("0"),
        daily_unrealized_profit_loss=Decimal("0"),
        open_position_count=6,
        symbol_position_quantity=Decimal("0.04"),
    )
    assert MaximumOpenPositionsRule().evaluate(
        order=sell, account=account_held, policy=policy
    ).level == RiskDecisionLevel.PASS


def test_daily_limit_blocks_entry_not_verified_exit() -> None:
    from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline

    src = inspect.getsource(LiveOrderSafetyPipeline)
    assert "DAILY_ORDER_LIMIT_EXCEEDED" in src
    assert "(not verified_exit) and daily_count >= int(policy.daily_order_limit)" in src


def test_duplicate_sell_outstanding_sot() -> None:
    open_sell = SimpleNamespace(
        side_code="SELL",
        status_code="ACCEPTED",
        remaining_quantity=Decimal("0.04"),
        outbox=None,
    )
    assert is_order_outstanding_for_sell(open_sell) is True
    filled = SimpleNamespace(
        side_code="SELL",
        status_code="FILLED",
        remaining_quantity=Decimal("0"),
        outbox=None,
    )
    assert is_order_outstanding_for_sell(filled) is False


def test_min_notional_sol_exit_9700_passes() -> None:
    blocked = evaluate_upbit_min_notional(
        broker_code="UPBIT",
        environment="LIVE",
        side="SELL",
        order_type="MARKET",
        quantity=Decimal("0.04"),
        price=None,
        market_krw_amount=Decimal("4999"),
    )
    assert blocked is not None
    ok = evaluate_upbit_min_notional(
        broker_code="UPBIT",
        environment="LIVE",
        side="SELL",
        order_type="MARKET",
        quantity=Decimal("0.04"),
        price=None,
        market_krw_amount=Decimal("9700"),
    )
    assert ok is None
    assert UPBIT_MIN_NOTIONAL_KRW == Decimal("5000")


def test_kill_pause_recovery_are_runtime_start_blockers() -> None:
    from stock_platform.trading.upbit_24x7_control import (
        REASON_ACCOUNT_PAUSED,
        REASON_ACTIVATION_INACTIVE,
        REASON_ARM_EXPIRED,
        REASON_KILL_SWITCH_ACTIVE,
        REASON_LIVE_OFF,
        REASON_RECOVERY_NOT_READY,
        REASON_TRADING_PAUSED,
        evaluate_runtime_start_gates,
    )

    src = inspect.getsource(evaluate_runtime_start_gates)
    assert "require_worker_running" in src
    gate_src = inspect.getsource(
        __import__(
            "stock_platform.trading.upbit_24x7_control",
            fromlist=["_evaluate_live_operating_gates"],
        )._evaluate_live_operating_gates
    )
    for code in (
        REASON_KILL_SWITCH_ACTIVE,
        REASON_ACCOUNT_PAUSED,
        REASON_TRADING_PAUSED,
        REASON_RECOVERY_NOT_READY,
        REASON_ACTIVATION_INACTIVE,
        REASON_LIVE_OFF,
        REASON_ARM_EXPIRED,
    ):
        assert code in gate_src


def test_quote_feed_restore_uses_hub_subscription_set() -> None:
    src = inspect.getsource(collect_upbit_symbols_from_hub)
    assert "list_subscriptions" in src
    assert "KRW-XRP" not in src
    assert "hardcode" not in src.lower()
