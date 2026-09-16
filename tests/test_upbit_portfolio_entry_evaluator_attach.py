"""Portfolio entry evaluator attach / slot-bound stale — focused (no REAL orders)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
    POLICY_BULLISH_STATE,
    PortfolioEntryContext,
    PortfolioEntryThresholds,
    SymbolEntrySnapshot,
    attach_portfolio_entry_context_to_hub,
)
from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.strategy_models import RealtimeStrategyConfig
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    StrategyRuntimeScope,
)


def _scope(uba: int = 1380) -> StrategyRuntimeScope:
    return StrategyRuntimeScope(
        user_id=1,
        account_kind=AccountKind.USER_BROKER,
        account_id=uba,
        strategy_id=1,
        strategy_version="t",
        market_type="CRYPTO",
        broker_code="UPBIT",
    )


def _event(symbol: str, price: Decimal, seq: int) -> RealtimeMarketEvent:
    now = datetime.now(timezone.utc)
    return RealtimeMarketEvent(
        broker_code="UPBIT",
        exchange_code="UPBIT",
        market_type="CRYPTO",
        symbol=symbol,
        event_type="TRADE",
        price=price,
        event_time=now,
        received_at=now,
        source_code="TEST",
        raw_sequence=seq,
        change_rate=None,
    )


def test_attach_patches_portfolio_mode_and_policy() -> None:
    scope = _scope()
    evaluator = MovingAverageStrategyEvaluator(
        scope, RealtimeStrategyConfig()  # defaults: CROSS_EVENT, portfolio_mode=False
    )
    consumer = MagicMock()
    consumer.scope = scope
    consumer.evaluator = evaluator

    registry = MagicMock()
    registry._lock = MagicMock()
    registry._lock.__enter__ = MagicMock(return_value=None)
    registry._lock.__exit__ = MagicMock(return_value=False)
    registry._by_scope = {"k": consumer}

    hub = MagicMock()
    hub.registry = registry

    ctx = PortfolioEntryContext(
        user_broker_account_id=1380,
        policy=POLICY_BULLISH_STATE,
        thresholds=PortfolioEntryThresholds(),
        by_symbol={
            "KRW-AAA": SymbolEntrySnapshot(
                symbol="KRW-AAA",
                selected_at=datetime.now(timezone.utc) - timedelta(hours=3),
                ai_recommendation="ALLOW",
                rsi14=50.0,
                volume_surge=1.0,
                bound_to_waiting_slot=True,
            )
        },
        refreshed_at=datetime.now(timezone.utc),
    )

    with (
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_entry_signal.build_portfolio_entry_context",
            return_value=ctx,
        ),
        patch(
            "stock_platform.realtime.market_data_hub.get_realtime_market_data_hub",
            return_value=hub,
        ),
    ):
        out = attach_portfolio_entry_context_to_hub(MagicMock(), 1380)

    assert out["attached"] == 1
    assert out["config_patched"] == 1
    assert evaluator.portfolio_entry_ctx is ctx
    assert evaluator.config.portfolio_mode is True
    assert evaluator.config.entry_signal_policy == POLICY_BULLISH_STATE


def test_warmup_then_bullish_block_records_telemetry() -> None:
    """충분한 tick 후 BULLISH BLOCK reason이 telemetry에 남는다."""

    from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
        portfolio_entry_telemetry,
    )

    scope = _scope(uba=99001)
    evaluator = MovingAverageStrategyEvaluator(
        scope,
        RealtimeStrategyConfig(
            short_window=3,
            long_window=5,
            portfolio_mode=True,
            entry_signal_policy=POLICY_BULLISH_STATE,
        ),
    )
    evaluator.portfolio_entry_ctx = PortfolioEntryContext(
        user_broker_account_id=99001,
        policy=POLICY_BULLISH_STATE,
        thresholds=PortfolioEntryThresholds(min_ma_separation_pct=0.05),
        by_symbol={
            "KRW-ZZZ": SymbolEntrySnapshot(
                symbol="KRW-ZZZ",
                selected_at=datetime.now(timezone.utc) - timedelta(hours=2),
                ai_recommendation="ALLOW",
                rsi14=55.0,
                volume_surge=1.2,
                bound_to_waiting_slot=True,
            )
        },
    )

    # declining prices → short <= long → BLOCK
    prices = [Decimal(str(p)) for p in (10, 9, 8, 7, 6, 5, 4, 3)]
    for i, price in enumerate(prices, start=1):
        evaluator.evaluate(_event("KRW-ZZZ", price, i))

    snap = portfolio_entry_telemetry.snapshot(99001)
    row = snap.get("KRW-ZZZ") or {}
    assert int(row.get("evaluation_count") or 0) > 0
    assert row.get("last_decision") == "BLOCK"
    assert row.get("last_block_reason") in {
        "SHORT_MA_NOT_ABOVE_LONG_MA",
        "WARMING_UP",
        "PREV_MA_NOT_READY",
        "MA_SEPARATION_TOO_SMALL",
    }
    assert evaluator.path_counters.get("ma_evaluator_called", 0) > 0
    assert evaluator.path_counters.get("portfolio_eval_called", 0) >= 0
