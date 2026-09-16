"""LIVE 1D timeframe alignment — unit only. production mutation 0, broker 0."""

from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from stock_platform.backtest.models import BacktestPrice
from stock_platform.backtest.strategy import (
    MovingAverageCrossStrategy,
    MovingAverageStrategyConfig,
)
from stock_platform.realtime.consumer_registry import ScopeConsumerRegistry
from stock_platform.realtime.daily_bar_seed import (
    fetch_upbit_current_day_close,
    required_completed_bars,
)
from stock_platform.realtime.hub_constants import ConsumerWarmupStatus
from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.runtime_bridge import _config_from_entry
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeStrategyConfig,
    uses_daily_bars,
)
from stock_platform.realtime.timeframe_bar import (
    RealtimeTimeframeBarAggregator,
    kst_trading_date,
)
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)


_KST = ZoneInfo("Asia/Seoul")
_EMPTY = RealtimePositionState(quantity=Decimal("0"), average_entry_price=None)


def _scope(*, strategy_id: int, account_id: int = 1380) -> StrategyRuntimeScope:
    return StrategyRuntimeScope(
        user_id=61,
        account_kind=AccountKind.USER_BROKER,
        account_id=account_id,
        strategy_id=strategy_id,
        strategy_version="1",
        market_type="CRYPTO",
        broker_code="UPBIT",
    )


def _daily_cfg() -> RealtimeStrategyConfig:
    return RealtimeStrategyConfig(
        short_window=5,
        long_window=20,
        cooldown_seconds=0,
        timeframe="1D",
    )


def _tick_at(
    symbol: str,
    price: str,
    *,
    event_time: datetime,
    received_at: datetime | None = None,
    seq: int | None = None,
) -> RealtimeMarketEvent:
    recv = received_at or datetime.now(timezone.utc)
    return RealtimeMarketEvent(
        broker_code="UPBIT",
        market_type="CRYPTO",
        symbol=symbol,
        event_type="TRADE",
        event_time=event_time,
        received_at=recv,
        exchange_code="UPBIT",
        price=Decimal(price),
        raw_sequence=seq,
    )


def _kst(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_KST)


def _sma(values: list[Decimal], window: int) -> Decimal:
    return sum(values[-window:], Decimal("0")) / Decimal(window)


def _cross_counts(closes: list[Decimal], *, short: int = 5, long: int = 20) -> tuple[int, int]:
    """Paper/LIVE CROSS_ABOVE · CROSS_BELOW 와 동일한 previous/current MA 교차."""

    golden = 0
    dead = 0
    prev_s: Decimal | None = None
    prev_l: Decimal | None = None
    for index in range(len(closes)):
        observed = closes[: index + 1]
        if len(observed) < short:
            continue
        short_avg = _sma(observed, short)
        long_avg = _sma(observed, long) if len(observed) >= long else None
        if (
            prev_s is not None
            and prev_l is not None
            and long_avg is not None
            and len(observed) >= long + 1
        ):
            if prev_s <= prev_l and short_avg > long_avg:
                golden += 1
            if prev_s >= prev_l and short_avg < long_avg:
                dead += 1
        prev_s = short_avg
        prev_l = long_avg
    return golden, dead


def _synthetic_daily_closes() -> list[Decimal]:
    """워밍업 이후 골든크로스→데드크로스가 생기도록 만든 daily close."""

    # 하락으로 시작해 READY 시점에 short < long 유지
    values = [Decimal(str(120 - i)) for i in range(20)]
    values.extend(
        [
            Decimal("100"),
            Decimal("99"),
            Decimal("112"),
            Decimal("125"),
            Decimal("138"),
            Decimal("145"),
            Decimal("120"),
            Decimal("100"),
            Decimal("85"),
            Decimal("70"),
        ]
    )
    return values


def test_required_completed_bars_matches_evaluator_deque() -> None:
    assert required_completed_bars(20) == 21
    assert uses_daily_bars("1D")
    assert uses_daily_bars("daily")
    assert not uses_daily_bars("")
    assert not uses_daily_bars("TICK")


def test_runtime_bridge_reads_timeframe_and_cooldown_bars() -> None:
    src = inspect.getsource(_config_from_entry)
    assert "timeframe" in src
    entry = SimpleNamespace(
        runtime=SimpleNamespace(
            parameter_payload={
                "symbol": "KRW-SOL",
                "timeframe": "1D",
                "short_window": 5,
                "long_window": 20,
                "stop_loss_ratio": "0.03",
                "take_profit_ratio": "0.06",
                "cooldown_seconds": 30,
                "indicator_configuration": {"cooldown_bars": 1},
            }
        )
    )
    cfg = _config_from_entry(entry)
    assert cfg.timeframe == "1D"
    assert cfg.uses_daily_bars()
    assert cfg.short_window == 5
    assert cfg.long_window == 20
    assert cfg.cooldown_seconds == 30
    assert cfg.cooldown_bars == 1


def test_raw_same_day_ticks_do_not_warmup_daily_ma() -> None:
    ev = MovingAverageStrategyEvaluator(_scope(strategy_id=17580), _daily_cfg())
    now = datetime.now(timezone.utc)
    day = _kst(2026, 8, 19, 10)
    for i in range(20):
        signal = ev.evaluate(
            _tick_at(
                "KRW-SOL",
                str(100 + i),
                event_time=day + timedelta(minutes=i),
                received_at=now,
                seq=i + 1,
            ),
            position=_EMPTY,
        )
        assert signal is None
    state = ev.get_state("KRW-SOL")
    assert len(state.prices) == 1
    assert ev.warmup_status("KRW-SOL") == ConsumerWarmupStatus.WARMING_UP


def test_same_day_100_ticks_keep_one_rolling_bar() -> None:
    ev = MovingAverageStrategyEvaluator(_scope(strategy_id=17580), _daily_cfg())
    now = datetime.now(timezone.utc)
    day = _kst(2026, 8, 19, 1)
    for i in range(100):
        ev.evaluate(
            _tick_at(
                "KRW-SOL",
                str(200 + i),
                event_time=day + timedelta(minutes=i),
                received_at=now,
                seq=i + 1,
            ),
            position=_EMPTY,
        )
    state = ev.get_state("KRW-SOL")
    assert len(state.prices) == 1
    assert state.prices[-1] == Decimal("299")
    rolling = ev._bars.current_bar("KRW-SOL")
    assert rolling is not None
    assert rolling.trade_date == date(2026, 8, 19)
    assert rolling.close_price == Decimal("299")
    assert rolling.open_price == Decimal("200")


def test_daily_history_seed_warmup() -> None:
    ev = MovingAverageStrategyEvaluator(_scope(strategy_id=17580), _daily_cfg())
    base = date(2026, 7, 20)
    twenty = [(base + timedelta(days=i), Decimal("100")) for i in range(20)]
    assert ev.seed_completed_closes("KRW-SOL", twenty) == 20
    assert ev.warmup_status("KRW-SOL") == ConsumerWarmupStatus.WARMING_UP
    twenty_one = twenty + [(date(2026, 8, 9), Decimal("101"))]
    assert ev.seed_completed_closes("KRW-SOL", twenty_one) == 21
    assert ev.warmup_status("KRW-SOL") == ConsumerWarmupStatus.READY
    assert ev.get_state("KRW-SOL").input_unit == "DAY"


def test_kst_midnight_rollover_appends_new_day_once() -> None:
    ev = MovingAverageStrategyEvaluator(_scope(strategy_id=17580), _daily_cfg())
    seed = [
        (date(2026, 8, 1) + timedelta(days=i), Decimal("100") + Decimal(i))
        for i in range(21)
    ]
    ev.seed_completed_closes("KRW-SOL", seed)
    now = datetime.now(timezone.utc)
    ev.evaluate(
        _tick_at(
            "KRW-SOL",
            "130",
            event_time=_kst(2026, 8, 22, 0, 1),
            received_at=now,
            seq=1,
        ),
        position=_EMPTY,
    )
    state = ev.get_state("KRW-SOL")
    assert state.last_bar_date == date(2026, 8, 22)
    length_after_first = len(state.prices)
    ev.evaluate(
        _tick_at(
            "KRW-SOL",
            "131",
            event_time=_kst(2026, 8, 22, 12),
            received_at=now,
            seq=2,
        ),
        position=_EMPTY,
    )
    assert len(ev.get_state("KRW-SOL").prices) == length_after_first
    ev.evaluate(
        _tick_at(
            "KRW-SOL",
            "140",
            event_time=_kst(2026, 8, 23, 0, 1),
            received_at=now,
            seq=3,
        ),
        position=_EMPTY,
    )
    assert ev.get_state("KRW-SOL").last_bar_date == date(2026, 8, 23)
    assert len(ev.get_state("KRW-SOL").prices) == length_after_first
    assert kst_trading_date(_kst(2026, 8, 22, 0, 0)) == date(2026, 8, 22)
    assert kst_trading_date(_kst(2026, 8, 21, 23, 59)) == date(2026, 8, 21)


def test_restart_bootstrap_current_day_does_not_duplicate() -> None:
    ev = MovingAverageStrategyEvaluator(_scope(strategy_id=17580), _daily_cfg())
    seed = [(date(2026, 7, 30) + timedelta(days=i), Decimal("50")) for i in range(21)]
    ev.seed_completed_closes("KRW-SOL", seed)
    ev.prime_current_day_bar(
        "KRW-SOL", trade_date=date(2026, 8, 20), close=Decimal("77")
    )
    before = list(ev.get_state("KRW-SOL").prices)
    now = datetime.now(timezone.utc)
    ev.evaluate(
        _tick_at(
            "KRW-SOL",
            "80",
            event_time=_kst(2026, 8, 20, 15),
            received_at=now,
            seq=1,
        ),
        position=_EMPTY,
    )
    after = list(ev.get_state("KRW-SOL").prices)
    assert len(after) == len(before)
    assert after[-1] == Decimal("80")


def test_fetch_current_day_bootstrap_is_not_signal_sot() -> None:
    today = date(2026, 8, 20)

    def _http(_market: str) -> list[dict[str, object]]:
        return [
            {
                "candle_date_time_kst": "2026-08-20T00:00:00",
                "trade_price": 12345,
            }
        ]

    got = fetch_upbit_current_day_close("KRW-SOL", today=today, http_get=_http)
    assert got == (today, Decimal("12345"))
    src = inspect.getsource(fetch_upbit_current_day_close)
    assert "LIVE 신호 SoT가 아님" in src


def test_stale_realtime_tick_does_not_update_daily_bar() -> None:
    ev = MovingAverageStrategyEvaluator(_scope(strategy_id=17580), _daily_cfg())
    seed = [(date(2026, 7, 30) + timedelta(days=i), Decimal("10")) for i in range(21)]
    ev.seed_completed_closes("KRW-SOL", seed)
    ev.prime_current_day_bar(
        "KRW-SOL", trade_date=date(2026, 8, 20), close=Decimal("11")
    )
    before = ev.get_state("KRW-SOL").prices[-1]
    stale = datetime.now(timezone.utc) - timedelta(seconds=120)
    signal = ev.evaluate(
        _tick_at(
            "KRW-SOL",
            "999",
            event_time=_kst(2026, 8, 20, 16),
            received_at=stale,
            seq=9,
        ),
        position=_EMPTY,
    )
    assert signal is None
    assert ev.get_state("KRW-SOL").prices[-1] == before


def test_backtest_golden_and_dead_cross_parity() -> None:
    closes = _synthetic_daily_closes()
    start = date(2026, 1, 1)
    bars = [
        BacktestPrice(
            trade_date=start + timedelta(days=i),
            open_price=close,
            high_price=close,
            low_price=close,
            close_price=close,
            volume=Decimal("1"),
        )
        for i, close in enumerate(closes)
    ]
    backtest = MovingAverageCrossStrategy(
        MovingAverageStrategyConfig(
            short_window=5,
            long_window=20,
            stop_loss_ratio=Decimal("0.90"),
            take_profit_ratio=Decimal("10"),
        )
    )
    golden_bt = 0
    for index in range(len(bars)):
        entered, reason = backtest.should_enter(prices=bars, index=index)
        if entered:
            assert reason == "MA_GOLDEN_CROSS"
            golden_bt += 1
    expected_golden, expected_dead = _cross_counts(closes)

    ev = MovingAverageStrategyEvaluator(
        _scope(strategy_id=17580),
        RealtimeStrategyConfig(
            short_window=5,
            long_window=20,
            cooldown_seconds=0,
            timeframe="1D",
            # MA 교차 패리티만 비교. SL/TP는 별도 테스트.
            stop_loss_ratio=Decimal("0.90"),
            take_profit_ratio=Decimal("10"),
        ),
    )
    now = datetime.now(timezone.utc)
    live_golden = 0
    live_dead = 0
    position = _EMPTY
    for i, bar in enumerate(bars):
        event_time = datetime(
            bar.trade_date.year,
            bar.trade_date.month,
            bar.trade_date.day,
            15,
            0,
            tzinfo=_KST,
        )
        signal = ev.evaluate(
            _tick_at(
                "KRW-SOL",
                str(bar.close_price),
                event_time=event_time,
                received_at=now,
                seq=i + 1,
            ),
            position=position,
        )
        if signal is None:
            continue
        if signal.reason_code == "MA_GOLDEN_CROSS":
            live_golden += 1
            position = RealtimePositionState(
                quantity=Decimal("1"),
                average_entry_price=bar.close_price,
            )
        elif signal.reason_code == "MA_DEAD_CROSS":
            live_dead += 1
            position = _EMPTY

    assert live_golden == golden_bt == expected_golden
    assert live_dead == expected_dead
    assert live_golden >= 1
    assert live_dead >= 1


def test_stop_loss_and_take_profit_use_tick_price() -> None:
    ev = MovingAverageStrategyEvaluator(_scope(strategy_id=17580), _daily_cfg())
    seed = [(date(2026, 7, 1) + timedelta(days=i), Decimal("100")) for i in range(21)]
    ev.seed_completed_closes("KRW-SOL", seed)
    held = RealtimePositionState(
        quantity=Decimal("1"), average_entry_price=Decimal("100")
    )
    now = datetime.now(timezone.utc)
    sl = ev.evaluate(
        _tick_at(
            "KRW-SOL",
            "96",
            event_time=_kst(2026, 8, 20, 11),
            received_at=now,
            seq=1,
        ),
        position=held,
    )
    assert sl is not None
    assert sl.reason_code == "STOP_LOSS"
    ev.reset()
    ev.seed_completed_closes("KRW-SOL", seed)
    tp = ev.evaluate(
        _tick_at(
            "KRW-SOL",
            "107",
            event_time=_kst(2026, 8, 20, 11),
            received_at=now,
            seq=1,
        ),
        position=held,
    )
    assert tp is not None
    assert tp.reason_code == "TAKE_PROFIT"


def test_xrp_sol_aggregator_isolation() -> None:
    ev = MovingAverageStrategyEvaluator(_scope(strategy_id=17580), _daily_cfg())
    now = datetime.now(timezone.utc)
    day = _kst(2026, 8, 19, 12)
    ev.evaluate(
        _tick_at("KRW-SOL", "200", event_time=day, received_at=now, seq=1),
        position=_EMPTY,
    )
    ev.evaluate(
        _tick_at("KRW-XRP", "500", event_time=day, received_at=now, seq=2),
        position=_EMPTY,
    )
    assert ev.get_state("KRW-SOL").prices[-1] == Decimal("200")
    assert ev.get_state("KRW-XRP").prices[-1] == Decimal("500")
    sol_bar = ev._bars.current_bar("KRW-SOL")
    xrp_bar = ev._bars.current_bar("KRW-XRP")
    assert sol_bar is not None and xrp_bar is not None
    assert sol_bar.close_price != xrp_bar.close_price


def test_multi_strategy_isolation() -> None:
    sol = MovingAverageStrategyEvaluator(_scope(strategy_id=17580), _daily_cfg())
    xrp = MovingAverageStrategyEvaluator(_scope(strategy_id=17483), _daily_cfg())
    now = datetime.now(timezone.utc)
    day = _kst(2026, 8, 19, 12)
    sol.evaluate(
        _tick_at("KRW-SOL", "10", event_time=day, received_at=now, seq=1),
        position=_EMPTY,
    )
    xrp.evaluate(
        _tick_at("KRW-XRP", "99", event_time=day, received_at=now, seq=1),
        position=_EMPTY,
    )
    assert sol.get_state("KRW-SOL").prices[-1] == Decimal("10")
    assert "KRW-SOL" not in xrp._by_symbol
    assert xrp.get_state("KRW-XRP").prices[-1] == Decimal("99")
    assert sol._bars.current_bar("KRW-XRP") is None


def test_tick_strategy_regression_still_uses_raw_prices() -> None:
    ev = MovingAverageStrategyEvaluator(
        _scope(strategy_id=1),
        RealtimeStrategyConfig(short_window=2, long_window=3, cooldown_seconds=0),
    )
    now = datetime.now(timezone.utc)
    signals = []
    for i, price in enumerate(["10", "9", "8", "11"]):
        sig = ev.evaluate(
            _tick_at(
                "005930",
                price,
                event_time=now + timedelta(seconds=i),
                received_at=now,
                seq=i + 1,
            )
        )
        if sig:
            signals.append(sig)
    assert signals
    assert signals[-1].reason_code == "MA_GOLDEN_CROSS"
    assert ev.get_state("005930").input_unit == "TICK"


def test_hub_registration_does_not_start_runner() -> None:
    from stock_platform.realtime import daily_bar_seed, ma_evaluator, timeframe_bar

    for module in (daily_bar_seed, ma_evaluator, timeframe_bar):
        src = inspect.getsource(module)
        assert "RealtimeExecutionRunner" not in src
        assert "LIVE ON" not in src


def test_registry_scope_keys_do_not_share_daily_state() -> None:
    registry = ScopeConsumerRegistry()
    sol_scope = _scope(strategy_id=17580)
    xrp_scope = _scope(strategy_id=17483)
    registry.register_consumer(
        sol_scope,
        ["KRW-SOL"],
        config=_daily_cfg(),
        runtime_status=RuntimeLifecycleStatus.CREATED,
    )
    registry.register_consumer(
        xrp_scope,
        ["KRW-XRP"],
        config=_daily_cfg(),
        runtime_status=RuntimeLifecycleStatus.PAUSED,
    )
    sol = registry.get_consumer(sol_scope.scope_key)
    xrp = registry.get_consumer(xrp_scope.scope_key)
    assert sol is not None and xrp is not None
    assert sol["strategy_id"] == 17580
    assert xrp["strategy_id"] == 17483
    assert sol["ma_input_unit"] == "DAY"
    assert xrp["ma_input_unit"] == "DAY"
    assert sol["runtime_status"] == RuntimeLifecycleStatus.CREATED.value
    assert xrp["runtime_status"] == RuntimeLifecycleStatus.PAUSED.value
    assert registry._by_scope[sol_scope.scope_key].evaluator is not registry._by_scope[
        xrp_scope.scope_key
    ].evaluator


def test_aggregator_prime_replace_same_day() -> None:
    agg = RealtimeTimeframeBarAggregator(scope_key="s", timeframe="1D")
    first = agg.prime(
        "KRW-SOL", trade_date=date(2026, 8, 20), close=Decimal("1")
    )
    second = agg.prime(
        "KRW-SOL", trade_date=date(2026, 8, 20), close=Decimal("2")
    )
    assert first.replaced_last is False
    assert second.replaced_last is True
    bar = agg.current_bar("KRW-SOL")
    assert bar is not None
    assert bar.close_price == Decimal("2")
