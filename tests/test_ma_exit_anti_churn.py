"""MA_DEAD_CROSS anti-churn — focused unit tests (no broker calls)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from stock_platform.realtime.hub_constants import SignalType
from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.ma_exit_policy import (
    DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS,
    MaExitThresholds,
    estimate_fee_aware_exit,
    evaluate_ma_dead_cross_gate,
    is_dead_cross_confirmed,
    is_protective_exit_reason,
    ma_separation_pct,
)
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


def _event(
    price: Decimal,
    *,
    seq: int,
    when: datetime | None = None,
    symbol: str = "KRW-SUI",
) -> RealtimeMarketEvent:
    now = when or datetime.now(timezone.utc)
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


def _cfg(**kwargs) -> RealtimeStrategyConfig:
    base = dict(
        short_window=5,
        long_window=20,
        cooldown_seconds=0,
        # MA 경로 테스트 시 SL이 가로채지 않도록 크게
        stop_loss_ratio=Decimal("0.90"),
        take_profit_ratio=Decimal("10"),
        exit_min_ma_separation_pct=0.03,
        ma_exit_min_holding_seconds=180,
        portfolio_mode=False,
    )
    base.update(kwargs)
    return RealtimeStrategyConfig(**base)


def _feed_warmup(ev: MovingAverageStrategyEvaluator, start_seq: int = 1) -> int:
    """장기 MA 워밍업 — 완만히 상승해 short>long 유지."""

    seq = start_seq
    for i in range(25):
        px = Decimal("100") + Decimal(i) * Decimal("0.5")
        ev.evaluate(
            _event(px, seq=seq),
            position=RealtimePositionState(
                quantity=Decimal("0"), average_entry_price=None
            ),
        )
        seq += 1
    return seq


def test_protective_reasons_unaffected_by_gate() -> None:
    assert is_protective_exit_reason("STOP_LOSS")
    assert is_protective_exit_reason("TAKE_PROFIT")
    assert is_protective_exit_reason("TRAILING_STOP")
    assert is_protective_exit_reason("KILL_SWITCH")
    assert not is_protective_exit_reason("MA_DEAD_CROSS")


def test_tiny_separation_not_confirmed() -> None:
    short = Decimal("99.999")
    long = Decimal("100")
    sep = ma_separation_pct(short, long)
    assert sep is not None and sep > -0.03
    assert not is_dead_cross_confirmed(
        short_ma=short,
        long_ma=long,
        exit_min_ma_separation_pct=0.03,
    )


def test_confirmed_negative_separation() -> None:
    short = Decimal("99.9")
    long = Decimal("100")
    assert is_dead_cross_confirmed(
        short_ma=short,
        long_ma=long,
        exit_min_ma_separation_pct=0.03,
    )


def test_dead_cross_tiny_sep_no_sell() -> None:
    """1) dead-cross + 미미한 역전폭 → no SELL (gate unit)."""

    th = MaExitThresholds(exit_min_ma_separation_pct=0.03)
    opened = datetime.now(timezone.utc) - timedelta(seconds=600)
    # short 거의 long — 역전폭 부족
    gate = evaluate_ma_dead_cross_gate(
        raw_dead_cross_event=True,
        confirming=False,
        short_ma=Decimal("99.999"),
        long_ma=Decimal("100"),
        opened_at=opened,
        thresholds=th,
        entry_price=Decimal("100"),
        quantity=Decimal("1"),
        current_price=Decimal("100"),
    )
    assert gate["decision"] == "CONFIRMING"
    assert gate["confirmed"] is False
    assert gate["block_reason"] == "MA_EXIT_SEPARATION_NOT_CONFIRMED"


def test_confirmed_sep_and_holding_emits_sell() -> None:
    """2) confirmed separation + holding >180s → SELL."""

    ev = MovingAverageStrategyEvaluator(_scope(), _cfg())
    seq = _feed_warmup(ev)
    opened = datetime.now(timezone.utc) - timedelta(seconds=300)
    pos = RealtimePositionState(
        quantity=Decimal("1"),
        average_entry_price=Decimal("110"),
        opened_at=opened,
    )
    signal = None
    for i in range(12):
        px = Decimal("100") - Decimal(i) * Decimal("2")
        signal = ev.evaluate(_event(px, seq=seq), position=pos)
        seq += 1
        if signal is not None and signal.reason_code == "MA_DEAD_CROSS":
            break
    assert signal is not None
    assert signal.signal_type == SignalType.SELL.value
    assert signal.reason_code == "MA_DEAD_CROSS"
    assert (signal.metadata or {}).get("profit_only_gate") is False


def test_holding_60s_ma_dead_cross_deferred() -> None:
    """3) holding 60s + MA dead-cross → strategy SELL 보류."""

    ev = MovingAverageStrategyEvaluator(_scope(), _cfg())
    seq = _feed_warmup(ev)
    opened = datetime.now(timezone.utc) - timedelta(seconds=60)
    # entry는 현재 MA대 근처 — SL(90%)에 안 걸리게
    pos = RealtimePositionState(
        quantity=Decimal("1"),
        average_entry_price=Decimal("112"),
        opened_at=opened,
    )
    signal = None
    for i in range(12):
        px = Decimal("110") - Decimal(i) * Decimal("1.5")
        signal = ev.evaluate(_event(px, seq=seq), position=pos)
        seq += 1
        if signal is not None:
            break
    assert signal is None or signal.reason_code != "MA_DEAD_CROSS"
    st = ev.get_state("KRW-SUI")
    assert st.ma_exit_confirming is True
    tel = st.last_ma_exit_telemetry or {}
    assert tel.get("decision") == "CONFIRMING"
    assert tel.get("block_reason") == "MA_EXIT_MIN_HOLDING"


def test_holding_60s_stop_loss_immediate() -> None:
    """4) holding 60s + STOP_LOSS → immediate SELL."""

    ev = MovingAverageStrategyEvaluator(
        _scope(),
        _cfg(stop_loss_ratio=Decimal("0.05"), take_profit_ratio=Decimal("0.5")),
    )
    opened = datetime.now(timezone.utc) - timedelta(seconds=60)
    pos = RealtimePositionState(
        quantity=Decimal("1"),
        average_entry_price=Decimal("1000"),
        opened_at=opened,
    )
    signal = ev.evaluate(
        _event(Decimal("940"), seq=1),
        position=pos,
    )
    assert signal is not None
    assert signal.reason_code == "STOP_LOSS"


def test_trailing_reason_is_protective() -> None:
    """5) TRAILING은 보호 경로 — min-hold gate 대상 아님."""

    assert is_protective_exit_reason("TRAILING_STOP")
    th = MaExitThresholds()
    gate = evaluate_ma_dead_cross_gate(
        raw_dead_cross_event=True,
        confirming=False,
        short_ma=Decimal("99"),
        long_ma=Decimal("100"),
        opened_at=datetime.now(timezone.utc) - timedelta(seconds=30),
        thresholds=th,
    )
    assert gate["decision"] == "CONFIRMING"


def test_net_loss_confirmed_still_sells() -> None:
    """6) holding >180s + net loss + confirmed → SELL (profit-only 금지)."""

    ev = MovingAverageStrategyEvaluator(_scope(), _cfg())
    seq = _feed_warmup(ev)
    opened = datetime.now(timezone.utc) - timedelta(seconds=400)
    pos = RealtimePositionState(
        quantity=Decimal("1"),
        average_entry_price=Decimal("120"),
        opened_at=opened,
        buy_fee=Decimal("0.06"),
    )
    signal = None
    for i in range(12):
        px = Decimal("100") - Decimal(i) * Decimal("2")
        signal = ev.evaluate(_event(px, seq=seq), position=pos)
        seq += 1
        if signal is not None and signal.reason_code == "MA_DEAD_CROSS":
            break
    assert signal is not None
    assert signal.reason_code == "MA_DEAD_CROSS"
    assert (signal.metadata or {}).get("profit_only_gate") is False
    fee = (signal.metadata or {}).get("fee_aware") or {}
    assert fee.get("estimated_net_pnl") is not None


def test_fee_only_same_price_observability() -> None:
    """7) fee-only same-price observability."""

    snap = estimate_fee_aware_exit(
        entry_price=Decimal("1110"),
        quantity=Decimal("8.98"),
        current_price=Decimal("1110"),
        buy_fee=Decimal("4.98"),
        fee_rate=0.0005,
    )
    assert snap["estimated_net_pnl"] is not None
    assert Decimal(str(snap["estimated_net_pnl"])) < 0


def test_bullish_recovery_resets_confirmation() -> None:
    """8) bullish 복귀 → confirmation reset."""

    th = MaExitThresholds(ma_exit_min_holding_seconds=180)
    opened = datetime.now(timezone.utc) - timedelta(seconds=60)
    first = evaluate_ma_dead_cross_gate(
        raw_dead_cross_event=True,
        confirming=False,
        short_ma=Decimal("99"),
        long_ma=Decimal("100"),
        opened_at=opened,
        thresholds=th,
    )
    assert first["decision"] == "CONFIRMING"
    reset = evaluate_ma_dead_cross_gate(
        raw_dead_cross_event=False,
        confirming=True,
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        opened_at=opened,
        thresholds=th,
    )
    assert reset["decision"] == "RESET"


def test_reentry_cooldown_reuses_entry_cooldown() -> None:
    """9/10) strategy_exit_reentry_cooldown = entry_cooldown SoT."""

    assert DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS == 180
    from stock_platform.operation.upbit_full_market.portfolio_service import (
        UpbitPortfolioService,
    )

    svc = UpbitPortfolioService.__new__(UpbitPortfolioService)
    pub = UpbitPortfolioService._ma_exit_policy_public(
        svc,
        risk_group_policy_json={},
        entry_cooldown_seconds=300,
    )
    assert pub["strategy_exit_reentry_cooldown_seconds"] == 300
    assert pub["ma_exit_applies_to_protective"] is False
    assert pub["ma_exit_profit_only_gate"] is False


def test_sui_regression_64s_no_immediate_strategy_sell() -> None:
    """SUI #1804 regression: 64s holding → MA strategy SELL 즉시 제출 안 됨."""

    ev = MovingAverageStrategyEvaluator(
        _scope(),
        _cfg(
            ma_exit_min_holding_seconds=180,
            exit_min_ma_separation_pct=0.03,
            stop_loss_ratio=Decimal("0.99"),
        ),
    )
    seq = _feed_warmup(ev)
    opened = datetime.now(timezone.utc) - timedelta(seconds=64)
    pos = RealtimePositionState(
        quantity=Decimal("8.98"),
        average_entry_price=Decimal("1110"),
        opened_at=opened,
        buy_fee=Decimal("4.98"),
    )
    signal = None
    for i in range(15):
        px = Decimal("110") - Decimal(i) * Decimal("1.5")
        signal = ev.evaluate(_event(px, seq=seq), position=pos)
        seq += 1
        if signal is not None:
            break
    assert signal is None
    st = ev.get_state("KRW-SUI")
    assert st.ma_exit_confirming is True
    assert (st.last_ma_exit_telemetry or {}).get("block_reason") == (
        "MA_EXIT_MIN_HOLDING"
    )
    # 같은 시점에 STOP_LOSS면 즉시 SELL
    sl_ev = MovingAverageStrategyEvaluator(
        _scope(),
        _cfg(stop_loss_ratio=Decimal("0.05"), ma_exit_min_holding_seconds=180),
    )
    sl = sl_ev.evaluate(
        _event(Decimal("1000"), seq=1, symbol="KRW-SUI"),
        position=RealtimePositionState(
            quantity=Decimal("1"),
            average_entry_price=Decimal("1110"),
            opened_at=opened,
        ),
    )
    assert sl is not None and sl.reason_code == "STOP_LOSS"


def test_no_duplicate_sell_while_confirming() -> None:
    """13) confirming 동안 중복 SELL 없음."""

    ev = MovingAverageStrategyEvaluator(_scope(), _cfg())
    seq = _feed_warmup(ev)
    opened = datetime.now(timezone.utc) - timedelta(seconds=30)
    pos = RealtimePositionState(
        quantity=Decimal("1"),
        average_entry_price=Decimal("110"),
        opened_at=opened,
    )
    emits = 0
    for i in range(10):
        px = Decimal("90") - Decimal(i)
        sig = ev.evaluate(_event(px, seq=seq), position=pos)
        seq += 1
        if sig is not None and sig.reason_code == "MA_DEAD_CROSS":
            emits += 1
    assert emits == 0


def test_gate_idempotent_reset_after_emit_state_clear() -> None:
    """14) emit 후 confirming 해제."""

    ev = MovingAverageStrategyEvaluator(_scope(), _cfg())
    seq = _feed_warmup(ev)
    opened = datetime.now(timezone.utc) - timedelta(seconds=400)
    pos = RealtimePositionState(
        quantity=Decimal("1"),
        average_entry_price=Decimal("120"),
        opened_at=opened,
    )
    signal = None
    for i in range(15):
        px = Decimal("90") - Decimal(i) * Decimal("2")
        signal = ev.evaluate(_event(px, seq=seq), position=pos)
        seq += 1
        if signal is not None:
            break
    assert signal is not None
    assert ev.get_state("KRW-SUI").ma_exit_confirming is False


@pytest.mark.parametrize(
    "reason",
    ["STOP_LOSS", "TAKE_PROFIT", "TRAILING_STOP", "KILL_SWITCH"],
)
def test_protective_not_gated_by_ma_policy(reason: str) -> None:
    assert is_protective_exit_reason(reason)
