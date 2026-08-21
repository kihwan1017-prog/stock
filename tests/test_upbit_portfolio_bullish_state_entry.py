"""Portfolio BULLISH_STATE entry policy — focused unit tests (no REAL orders)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
    POLICY_BULLISH_STATE,
    POLICY_CROSS_EVENT,
    PortfolioEntryContext,
    PortfolioEntryThresholds,
    SymbolEntrySnapshot,
    evaluate_bullish_state_entry,
    normalize_entry_policy,
)
from stock_platform.realtime.hub_constants import SignalType
from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeStrategyConfig,
)
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    StrategyRuntimeScope,
)


def _scope() -> StrategyRuntimeScope:
    return StrategyRuntimeScope(
        user_id=1,
        account_kind=AccountKind.USER_BROKER,
        account_id=1380,
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


def test_normalize_policy_aliases() -> None:
    assert normalize_entry_policy("TREND_STATE") == POLICY_BULLISH_STATE
    assert normalize_entry_policy("bullish_state") == POLICY_BULLISH_STATE
    assert normalize_entry_policy(None) == POLICY_CROSS_EVENT


def test_bullish_state_short_above_long_passes() -> None:
    ok, reason, _ = evaluate_bullish_state_entry(
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        event_time=datetime.now(timezone.utc),
        snap=SymbolEntrySnapshot(
            symbol="KRW-AAA",
            selected_at=datetime.now(timezone.utc),
            ai_recommendation="ALLOW",
            rsi14=55.0,
            volume_surge=1.2,
        ),
        thresholds=PortfolioEntryThresholds(min_ma_separation_pct=0.05),
    )
    assert ok is True
    assert reason is None


def test_bullish_state_short_not_above_blocks() -> None:
    ok, reason, _ = evaluate_bullish_state_entry(
        short_ma=Decimal("99"),
        long_ma=Decimal("100"),
        event_time=datetime.now(timezone.utc),
        snap=SymbolEntrySnapshot(
            symbol="KRW-AAA",
            selected_at=datetime.now(timezone.utc),
            ai_recommendation="ALLOW",
            rsi14=55.0,
            volume_surge=1.2,
        ),
        thresholds=PortfolioEntryThresholds(),
    )
    assert ok is False
    assert reason == "SHORT_MA_NOT_ABOVE_LONG_MA"


def test_bullish_state_rsi_high_blocks() -> None:
    ok, reason, _ = evaluate_bullish_state_entry(
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        event_time=datetime.now(timezone.utc),
        snap=SymbolEntrySnapshot(
            symbol="KRW-AAA",
            selected_at=datetime.now(timezone.utc),
            ai_recommendation="ALLOW",
            rsi14=75.0,
            volume_surge=1.2,
        ),
        thresholds=PortfolioEntryThresholds(rsi_max=70.0),
    )
    assert ok is False
    assert reason == "RSI_TOO_HIGH"


def test_bullish_state_volume_fail_blocks() -> None:
    ok, reason, _ = evaluate_bullish_state_entry(
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        event_time=datetime.now(timezone.utc),
        snap=SymbolEntrySnapshot(
            symbol="KRW-AAA",
            selected_at=datetime.now(timezone.utc),
            ai_recommendation="ALLOW",
            rsi14=55.0,
            volume_surge=0.2,
        ),
        thresholds=PortfolioEntryThresholds(min_volume_surge=0.8),
    )
    assert ok is False
    assert reason == "VOLUME_SURGE_TOO_LOW"


def test_bullish_state_ai_hold_blocks() -> None:
    ok, reason, _ = evaluate_bullish_state_entry(
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        event_time=datetime.now(timezone.utc),
        snap=SymbolEntrySnapshot(
            symbol="KRW-AAA",
            selected_at=datetime.now(timezone.utc),
            ai_recommendation="HOLD",
            rsi14=55.0,
            volume_surge=1.2,
        ),
        thresholds=PortfolioEntryThresholds(),
    )
    assert ok is False
    assert reason == "AI_SELECTION_NOT_ALLOW"


def test_bullish_state_candidate_stale_blocks() -> None:
    ok, reason, _ = evaluate_bullish_state_entry(
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        event_time=datetime.now(timezone.utc),
        snap=SymbolEntrySnapshot(
            symbol="KRW-AAA",
            selected_at=datetime.now(timezone.utc) - timedelta(hours=2),
            ai_recommendation="ALLOW",
            rsi14=55.0,
            volume_surge=1.2,
        ),
        thresholds=PortfolioEntryThresholds(max_candidate_age_seconds=1800),
    )
    assert ok is False
    assert reason == "CANDIDATE_STALE"


def test_bullish_state_feed_stale_blocks() -> None:
    ok, reason, _ = evaluate_bullish_state_entry(
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        event_time=datetime.now(timezone.utc) - timedelta(seconds=120),
        snap=SymbolEntrySnapshot(
            symbol="KRW-AAA",
            selected_at=datetime.now(timezone.utc),
            ai_recommendation="ALLOW",
            rsi14=55.0,
            volume_surge=1.2,
        ),
        thresholds=PortfolioEntryThresholds(max_feed_age_seconds=30),
    )
    assert ok is False
    assert reason == "FEED_STALE"


def test_cross_event_regression_still_requires_cross() -> None:
    """FIXED/CROSS_EVENT: already-bullish state does not BUY."""

    ev = MovingAverageStrategyEvaluator(
        _scope(),
        RealtimeStrategyConfig(
            short_window=3,
            long_window=5,
            cooldown_seconds=0,
            portfolio_mode=False,
            entry_signal_policy=POLICY_CROSS_EVENT,
        ),
    )
    # seed prices already short>long without a fresh cross edge
    prices = [Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("12")]
    for i, p in enumerate(prices):
        sig = ev.evaluate(
            _event("KRW-X", p, i + 1),
            position=RealtimePositionState(quantity=Decimal("0"), average_entry_price=None),
            allow_signal=True,
        )
    # last tick may or may not cross depending on averages — force no-cross path:
    # after warm, feed flat bullish ticks
    for i in range(10):
        sig = ev.evaluate(
            _event("KRW-X", Decimal("12"), 100 + i),
            position=RealtimePositionState(quantity=Decimal("0"), average_entry_price=None),
            allow_signal=True,
        )
        assert sig is None or sig.signal_type != SignalType.BUY.value or sig.reason_code == "MA_GOLDEN_CROSS"


def test_portfolio_bullish_emits_reason() -> None:
    ev = MovingAverageStrategyEvaluator(
        _scope(),
        RealtimeStrategyConfig(
            short_window=3,
            long_window=5,
            cooldown_seconds=0,
            portfolio_mode=True,
            entry_signal_policy=POLICY_BULLISH_STATE,
        ),
    )
    ev.portfolio_entry_ctx = PortfolioEntryContext(
        user_broker_account_id=1380,
        policy=POLICY_BULLISH_STATE,
        thresholds=PortfolioEntryThresholds(
            min_ma_separation_pct=0.0,
            rsi_max=70.0,
            min_volume_surge=0.0,
            max_candidate_age_seconds=3600,
            max_feed_age_seconds=60,
        ),
        by_symbol={
            "KRW-Y": SymbolEntrySnapshot(
                symbol="KRW-Y",
                selected_at=datetime.now(timezone.utc),
                ai_recommendation="ALLOW",
                rsi14=50.0,
                volume_surge=1.0,
            )
        },
    )
    # warmup + rising to ensure short>long
    seq = 1
    last = None
    for p in [Decimal("10")] * 5 + [Decimal("11"), Decimal("12"), Decimal("13")]:
        last = ev.evaluate(
            _event("KRW-Y", p, seq),
            position=RealtimePositionState(quantity=Decimal("0"), average_entry_price=None),
            allow_signal=True,
        )
        seq += 1
    assert last is not None
    assert last.signal_type == SignalType.BUY.value
    assert last.reason_code == "PORTFOLIO_BULLISH_STATE_ENTRY"


def test_portfolio_bullish_no_entry_when_short_below() -> None:
    ev = MovingAverageStrategyEvaluator(
        _scope(),
        RealtimeStrategyConfig(
            short_window=3,
            long_window=5,
            cooldown_seconds=0,
            portfolio_mode=True,
            entry_signal_policy=POLICY_BULLISH_STATE,
        ),
    )
    ev.portfolio_entry_ctx = PortfolioEntryContext(
        user_broker_account_id=1380,
        policy=POLICY_BULLISH_STATE,
        thresholds=PortfolioEntryThresholds(
            min_ma_separation_pct=0.0,
            min_volume_surge=0.0,
            max_candidate_age_seconds=3600,
        ),
        by_symbol={
            "KRW-Z": SymbolEntrySnapshot(
                symbol="KRW-Z",
                selected_at=datetime.now(timezone.utc),
                ai_recommendation="ALLOW",
                rsi14=50.0,
                volume_surge=1.0,
            )
        },
    )
    seq = 1
    last = None
    for p in [Decimal("20")] * 5 + [Decimal("10"), Decimal("9"), Decimal("8")]:
        last = ev.evaluate(
            _event("KRW-Z", p, seq),
            position=RealtimePositionState(quantity=Decimal("0"), average_entry_price=None),
            allow_signal=True,
        )
        seq += 1
        if last is not None and last.signal_type == SignalType.BUY.value:
            pytest.fail("should not BUY when short MA below long MA")
