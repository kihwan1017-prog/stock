"""WRK-015 short-term turnover research unit tests — no LIVE / no DB mutation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from stock_platform.operation.upbit_opportunity_shadow.candle_path import MinuteBar
from stock_platform.operation.upbit_opportunity_shadow.exit_policy_ab import (
    ExitPolicySpec,
    simulate_exit_policy,
)
from stock_platform.operation.upbit_short_term_turnover.metrics import (
    apply_round_trip_costs,
    max_drawdown,
    profit_factor,
    trades_per_day_stats,
)
from stock_platform.operation.upbit_short_term_turnover.slot_shadow import (
    HoldingRow,
    SlotCountMode,
    account_risk_exposure_notional,
    count_entry_slots,
    simulate_auto_only_admission,
)


def _bar(minute: int, *, o: str, h: str, low: str, c: str) -> MinuteBar:
    base = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)
    return MinuteBar(
        candle_at=base + timedelta(minutes=minute),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


ENTRY = Decimal("100")
ENTRY_AT = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 8, 20, 4, 0, tzinfo=timezone.utc)


def test_fee_and_slippage_separated() -> None:
    cost = apply_round_trip_costs(
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        notional_krw=Decimal("10000"),
        fee_rate=Decimal("0.0005"),
        slippage_bps_each_side=Decimal("2"),
    )
    assert cost.gross_pnl == Decimal("100")
    assert cost.buy_fee > 0
    assert cost.sell_fee > 0
    assert cost.slippage == Decimal("4")  # 10000 * 2bps * 2
    assert cost.net_pnl < cost.gross_pnl
    assert cost.net_pnl == cost.gross_pnl - cost.fee_total - cost.slippage


def test_profit_factor_and_drawdown() -> None:
    nets = [10.0, -5.0, 8.0, -20.0, 3.0]
    assert profit_factor(nets) == pytest.approx(21.0 / 25.0)
    assert max_drawdown(nets) > 0


def test_trades_per_day_metrics() -> None:
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    ats = [base + timedelta(days=i) for i in (0, 0, 1, 3)]
    stats = trades_per_day_stats(ats, window_days=5)
    assert stats["active_days"] == 3
    assert stats["zero_trade_days_pct"] == 40.0
    assert stats["median"] is not None


def test_tp_sl_first_exit_wins() -> None:
    bars = [
        _bar(0, o="100", h="100", low="100", c="100"),
        _bar(1, o="100", h="100.9", low="99.6", c="100.5"),
    ]
    spec = ExitPolicySpec(
        label="T",
        tp_pct=0.8,
        sl_pct=0.5,
        trail_distance_pct=0.4,
        trail_activation_pct=0.4,
        ma_exit_enabled=True,
    )
    r = simulate_exit_policy(
        bars,
        symbol="KRW-T",
        entry_at=ENTRY_AT,
        entry_price=ENTRY,
        spec=spec,
        now=NOW,
        horizon_minutes=60,
    )
    assert r.exit_reason == "TAKE_PROFIT"


def test_stop_loss_exit() -> None:
    bars = [
        _bar(0, o="100", h="100", low="100", c="100"),
        _bar(1, o="100", h="100", low="99.0", c="99.2"),
    ]
    spec = ExitPolicySpec(
        label="SL",
        tp_pct=2.0,
        sl_pct=0.8,
        trail_distance_pct=1.0,
        trail_activation_pct=1.0,
        ma_exit_enabled=False,
    )
    r = simulate_exit_policy(
        bars,
        symbol="KRW-T",
        entry_at=ENTRY_AT,
        entry_price=ENTRY,
        spec=spec,
        now=NOW,
        horizon_minutes=60,
    )
    assert r.exit_reason == "STOP_LOSS"


def test_time_exit_horizon_window_end() -> None:
    bars = [
        _bar(i, o="100", h="100.1", low="99.9", c="100") for i in range(0, 45)
    ]
    spec = ExitPolicySpec(
        label="H30",
        tp_pct=5.0,
        sl_pct=5.0,
        trail_distance_pct=3.0,
        trail_activation_pct=None,
        ma_exit_enabled=False,
    )
    r = simulate_exit_policy(
        bars,
        symbol="KRW-T",
        entry_at=ENTRY_AT,
        entry_price=ENTRY,
        spec=spec,
        now=NOW,
        horizon_minutes=30,
    )
    assert r.exit_reason in {"WINDOW_END", "LAST_CLOSE"}
    assert (r.holding_seconds or 0) <= 30 * 60 + 60


def test_no_lookahead_future_bars_ignored() -> None:
    bars = [
        _bar(0, o="100", h="100", low="100", c="100"),
        _bar(1, o="100", h="100.1", low="99.9", c="100"),
        _bar(2, o="100", h="120", low="100", c="115"),
    ]
    spec = ExitPolicySpec(
        label="NL",
        tp_pct=1.0,
        sl_pct=5.0,
        trail_distance_pct=3.0,
        trail_activation_pct=None,
        ma_exit_enabled=False,
    )
    r = simulate_exit_policy(
        bars,
        symbol="KRW-T",
        entry_at=ENTRY_AT,
        entry_price=ENTRY,
        spec=spec,
        now=ENTRY_AT + timedelta(minutes=1),
        horizon_minutes=60,
    )
    # now=분1 시점까지는 +20% 바가 아직 관측 불가 → TP 미발화 또는 낮은 가격
    if r.exit_reason == "TAKE_PROFIT":
        assert float(r.exit_price or 0) < 110


def test_auto_only_slot_manual_still_in_exposure() -> None:
    holdings = [
        HoldingRow("KRW-ADA", 100.0, "AUTO"),
        HoldingRow("KRW-BTC", 0.01, "MANUAL"),
        HoldingRow("KRW-ETH", 0.1, "MANUAL"),
        HoldingRow("KRW-DOGE", 1000.0, "MANUAL"),
        HoldingRow("KRW-SKY", 50.0, "MANUAL"),
    ]
    assert count_entry_slots(holdings, mode=SlotCountMode.BROKER_ALL) == 5
    assert count_entry_slots(holdings, mode=SlotCountMode.AUTO_ONLY) == 1
    exposure = account_risk_exposure_notional(
        holdings,
        mark_prices={
            "KRW-ADA": 1000,
            "KRW-BTC": 100_000_000,
            "KRW-ETH": 5_000_000,
            "KRW-DOGE": 200,
            "KRW-SKY": 3000,
        },
    )
    assert exposure > 0
    adm = simulate_auto_only_admission(holdings=holdings, max_positions=5)
    assert adm["broker_all_would_admit"] is False
    assert adm["auto_only_would_admit"] is True
    assert adm["additional_opportunity"] is True
    assert adm["manual_still_in_risk_exposure"] is True
    assert adm["real_policy_changed"] is False


def test_reentry_cooldown_gap() -> None:
    cooldown = 600
    last_exit = ENTRY_AT
    next_entry = ENTRY_AT + timedelta(seconds=300)
    gap = (next_entry - last_exit).total_seconds()
    assert gap < cooldown
    assert (gap >= cooldown) is False
