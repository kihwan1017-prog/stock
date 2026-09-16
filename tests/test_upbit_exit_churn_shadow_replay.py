"""Exit/churn shadow replay — research only."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from stock_platform.operation.upbit_opportunity_shadow.candle_path import MinuteBar
from stock_platform.operation.upbit_opportunity_shadow.exit_churn_shadow_replay import (
    FrozenRoundTrip,
    ReplayMaSpec,
    apply_cooldown_skips,
    e0_kpis,
    frozen_from_audit_row,
    simulate_ma_exit_replay,
)
from stock_platform.realtime.ma_exit_policy import is_protective_exit_reason


def _bar(minute: int, *, o: str, h: str, low: str, c: str) -> MinuteBar:
    base = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
    from datetime import timedelta

    return MinuteBar(
        candle_at=base + timedelta(minutes=minute),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


def test_e0_kpis_equality() -> None:
    row = {
        "binding_id": 1,
        "symbol": "KRW-TEST",
        "buy_time_kst": "2026-08-23T10:00:00+09:00",
        "sell_time_kst": "2026-08-23T10:05:00+09:00",
        "buy_price": 100.0,
        "sell_price": 99.0,
        "quantity": 100.0,
        "buy_amount": 10000.0,
        "gross_pnl": -100.0,
        "buy_fee": 5.0,
        "sell_fee": 5.0,
        "total_fee": 10.0,
        "net_pnl": -110.0,
        "exit_reason": "MA_DEAD_CROSS",
        "path": {"insufficient": False},
    }
    trip = frozen_from_audit_row(row)
    k = e0_kpis([trip])
    assert k["net_pnl"] == pytest.approx(-110.0)
    assert k["sample_count"] == 1


def test_stop_loss_precedence_over_ma_delay() -> None:
    trip = FrozenRoundTrip(
        trade_id=1,
        symbol="KRW-TEST",
        entry_time=datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc),
        entry_price=Decimal("100"),
        quantity=Decimal("100"),
        buy_amount=Decimal("10000"),
        buy_fee=Decimal("5"),
        sell_fee=Decimal("5"),
        actual_exit_time=datetime(2026, 8, 23, 0, 10, tzinfo=timezone.utc),
        actual_exit_price=Decimal("94"),
        actual_exit_reason="MA_DEAD_CROSS",
        actual_gross_pnl=-600,
        actual_total_fee=10,
        actual_net_pnl=-610,
    )
    bars = [
        _bar(0, o="100", h="100", low="100", c="100"),
        _bar(1, o="100", h="100", low="94", c="95"),
    ]
    spec = ReplayMaSpec(
        label="E1B_confirm3",
        group="E1",
        confirm_evaluations=3,
        sl_pct=5.0,
    )
    r = simulate_ma_exit_replay(bars, trip, spec)
    assert r["exit_reason"] == "STOP_LOSS"
    assert is_protective_exit_reason("STOP_LOSS")


def test_cooldown_skips_reentry() -> None:
    t1 = FrozenRoundTrip(
        trade_id=1,
        symbol="KRW-SUI",
        entry_time=datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc),
        entry_price=Decimal("100"),
        quantity=Decimal("1"),
        buy_amount=Decimal("100"),
        buy_fee=Decimal("0.05"),
        sell_fee=Decimal("0.05"),
        actual_exit_time=datetime(2026, 8, 23, 0, 10, tzinfo=timezone.utc),
        actual_exit_price=Decimal("99"),
        actual_exit_reason="MA_DEAD_CROSS",
        actual_gross_pnl=-1,
        actual_total_fee=0.1,
        actual_net_pnl=-1.1,
    )
    t2 = FrozenRoundTrip(
        trade_id=2,
        symbol="KRW-SUI",
        entry_time=datetime(2026, 8, 23, 0, 12, tzinfo=timezone.utc),
        entry_price=Decimal("100"),
        quantity=Decimal("1"),
        buy_amount=Decimal("100"),
        buy_fee=Decimal("0.05"),
        sell_fee=Decimal("0.05"),
        actual_exit_time=datetime(2026, 8, 23, 0, 20, tzinfo=timezone.utc),
        actual_exit_price=Decimal("99"),
        actual_exit_reason="MA_DEAD_CROSS",
        actual_gross_pnl=-1,
        actual_total_fee=0.1,
        actual_net_pnl=-1.1,
    )
    skipped = apply_cooldown_skips([t1, t2], cooldown_minutes=15)
    assert 2 in skipped
    assert 1 not in skipped
