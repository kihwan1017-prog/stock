"""STEP 8-5-9 — Realtime Hub / Scope Registry unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from stock_platform.realtime.consumer_registry import (
    ScopeConsumerRegistry,
    ScopeRequiredError,
)
from stock_platform.realtime.hub_constants import ConsumerWarmupStatus
from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.market_data_hub import (
    RealtimeMarketDataHub,
    reset_realtime_market_data_hub_for_tests,
)
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.models import MarketEventType, RealtimeQuote
from stock_platform.realtime.scoped_signal_pipeline import (
    reset_signal_dedup_for_tests,
)
from stock_platform.realtime.strategy_models import RealtimeStrategyConfig
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)
from tests.migration_helpers import alembic_current_head, assert_revision_exists


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_realtime_market_data_hub_for_tests()
    reset_signal_dedup_for_tests()
    yield
    reset_realtime_market_data_hub_for_tests()
    reset_signal_dedup_for_tests()


def _scope(
    *,
    user_id: int = 1,
    account_id: int = 10,
    strategy_id: int = 100,
    version: str = "1",
    broker: str = "PAPER",
    market: str = "STOCK",
    kind: AccountKind = AccountKind.PAPER,
) -> StrategyRuntimeScope:
    return StrategyRuntimeScope(
        user_id=user_id,
        account_kind=kind,
        account_id=account_id,
        strategy_id=strategy_id,
        strategy_version=version,
        market_type=market,
        broker_code=broker,
    )


def _event(
    price: str,
    *,
    symbol: str = "005930",
    broker: str = "PAPER",
    market: str = "STOCK",
    seq: int | None = None,
    age_seconds: float = 0,
) -> RealtimeMarketEvent:
    now = datetime.now(timezone.utc)
    return RealtimeMarketEvent(
        broker_code=broker,
        market_type=market,
        symbol=symbol,
        event_type="TICKER",
        event_time=now,
        received_at=now - timedelta(seconds=age_seconds),
        price=Decimal(price),
        change_rate=Decimal("0.01"),
        raw_sequence=seq,
    )


def test_alembic_single_head_unchanged() -> None:
    # STEP 8-5-9는 Migration 없음 — 단일 head + 선행 revision 체인만 확인
    head = alembic_current_head()
    assert head
    assert_revision_exists("y2c3d4e5f6a7")
    assert_revision_exists(head)


def test_scope_less_register_blocked() -> None:
    reg = ScopeConsumerRegistry()
    with pytest.raises(ScopeRequiredError):
        reg.register_consumer(None, ["005930"])


def test_scope_state_isolation() -> None:
    a = _scope(user_id=1, account_id=11, strategy_id=1)
    b = _scope(user_id=2, account_id=22, strategy_id=1)
    ea = MovingAverageStrategyEvaluator(
        a, RealtimeStrategyConfig(short_window=2, long_window=3)
    )
    eb = MovingAverageStrategyEvaluator(
        b, RealtimeStrategyConfig(short_window=2, long_window=3)
    )
    for p in ["10", "9", "8"]:
        ea.evaluate(_event(p))
        eb.evaluate(_event(p))
    assert len(ea.get_state("005930").prices) == 3
    assert len(eb.get_state("005930").prices) == 3
    # 동일 심볼이라도 객체 분리
    assert ea.get_state("005930") is not eb.get_state("005930")


def test_warmup_no_signal_until_ready() -> None:
    ev = MovingAverageStrategyEvaluator(
        _scope(),
        RealtimeStrategyConfig(short_window=2, long_window=3, cooldown_seconds=0),
    )
    out = ev.evaluate(_event("10"))
    assert out is None
    assert ev.warmup_status("005930") == ConsumerWarmupStatus.WARMING_UP


def test_golden_cross_and_duplicate_block() -> None:
    ev = MovingAverageStrategyEvaluator(
        _scope(),
        RealtimeStrategyConfig(short_window=2, long_window=3, cooldown_seconds=0),
    )
    signals = []
    for i, p in enumerate(["10", "9", "8", "11"]):
        sig = ev.evaluate(_event(p, seq=i + 1))
        if sig:
            signals.append(sig)
    assert signals
    assert signals[-1].signal_type == "BUY"
    assert signals[-1].reason_code == "MA_GOLDEN_CROSS"
    assert signals[-1].scope_key
    assert signals[-1].signal_id
    assert signals[-1].fingerprint
    # 동일 sequence 재주입 차단
    assert ev.evaluate(_event("11", seq=4)) is None


def test_stale_event_ignored() -> None:
    ev = MovingAverageStrategyEvaluator(
        _scope(),
        RealtimeStrategyConfig(short_window=2, long_window=3),
    )
    assert ev.evaluate(_event("10", age_seconds=100)) is None


def test_hub_subscription_dedup_and_fanout() -> None:
    hub = RealtimeMarketDataHub()
    s1 = _scope(
        user_id=1,
        account_id=1,
        strategy_id=1,
        broker="PAPER",
        market="CRYPTO",
    )
    s2 = _scope(
        user_id=2,
        account_id=2,
        strategy_id=2,
        broker="PAPER",
        market="CRYPTO",
    )
    hub.register_consumer(s1, ["KRW-BTC"])
    hub.register_consumer(s2, ["KRW-BTC"])
    subs = hub.registry.list_subscriptions()
    assert len(subs) == 1
    assert subs[0]["broker_code"] == "UPBIT"
    assert subs[0]["scope_count"] == 2

    now = datetime.now(timezone.utc)
    quote = RealtimeQuote(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        event_type=MarketEventType.TICKER,
        trade_price=Decimal("100"),
        opening_price=None,
        high_price=None,
        low_price=None,
        previous_close_price=None,
        change_price=None,
        change_rate=Decimal("0"),
        accumulated_volume=None,
        trade_volume=None,
        event_time=now,
        received_at=now,
        source_code="TEST",
    )
    # warm-up — no signal yet
    hub.ingest_quote_sync(quote)
    assert hub.registry.active_scope_count() == 2

    freed = hub.unregister_consumer(s1)
    assert not freed  # s2 still subscribed
    freed = hub.unregister_consumer(s2)
    assert freed  # last consumer


def test_pause_blocks_signal_keeps_state() -> None:
    hub = RealtimeMarketDataHub()
    scope = _scope()
    hub.register_consumer(
        scope,
        ["005930"],
        config=RealtimeStrategyConfig(
            short_window=2, long_window=3, cooldown_seconds=0
        ),
    )
    hub.registry.set_runtime_status(
        scope.scope_key,
        RuntimeLifecycleStatus.PAUSED,
        pause_reason="recovery",
    )
    for i, p in enumerate(["10", "9", "8", "11"]):
        sigs = hub.registry.dispatch(_event(p, seq=i + 1))
        assert sigs == []
    # warm-up may complete under pause
    st = hub.registry.get_consumer(scope.scope_key)
    assert st is not None
    assert st["runtime_status"] == "PAUSED"


def test_live_paper_scopes_separate() -> None:
    paper = _scope(kind=AccountKind.PAPER, broker="PAPER", account_id=1)
    live = StrategyRuntimeScope(
        user_id=1,
        account_kind=AccountKind.USER_BROKER,
        account_id=99,
        strategy_id=1,
        strategy_version="1",
        market_type="CRYPTO",
        broker_code="UPBIT",
    )
    assert paper.scope_key != live.scope_key
    reg = ScopeConsumerRegistry()
    reg.register_consumer(paper, ["KRW-BTC"])
    reg.register_consumer(live, ["KRW-BTC"])
    assert reg.active_scope_count() == 2


def test_deprecated_runner_status_uses_hub() -> None:
    from stock_platform.realtime.bus import RealtimeQuoteBus
    from stock_platform.realtime.signal_bus import RealtimeSignalBus
    from stock_platform.realtime.strategy_runner import RealtimeStrategyRunner

    runner = RealtimeStrategyRunner(
        quote_bus=RealtimeQuoteBus(),
        signal_bus=RealtimeSignalBus(),
    )
    status = runner.status()
    assert status["deprecated"] is True
    assert status["mode"] == "SCOPE_REGISTRY_HUB"
