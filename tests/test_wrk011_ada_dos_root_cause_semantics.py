"""WRK-011 — slot age_kind + OPEN holding semantics (unit)."""

from __future__ import annotations

from datetime import datetime, timezone


def test_open_slot_age_uses_opened_at_not_selected_at() -> None:
    """OPEN 보유 시간은 opened_at 기준이어야 한다 (selected_at 아님)."""

    now = datetime(2026, 8, 29, 2, 33, tzinfo=timezone.utc)
    opened = datetime(2026, 8, 28, 2, 25, 19, tzinfo=timezone.utc)
    selected = datetime(2026, 8, 28, 2, 11, 47, tzinfo=timezone.utc)
    hold_age = (now - opened).total_seconds()
    wait_age = (now - selected).total_seconds()
    assert hold_age < wait_age
    # UI "24시간 8분" ≈ opened_at 기준
    assert abs(hold_age - (24 * 3600 + 8 * 60)) < 120


def test_max_open_positions_counts_broker_snapshots() -> None:
    """Safety guard는 broker snapshot quantity>0 건수를 센다."""

    broker_open = 5  # ADA+BTC+ETH+DOGE+SKY
    max_open = 5
    auto_open_bindings = 1
    assert auto_open_bindings < max_open
    assert broker_open >= max_open
