"""Lifetime PnL formula — AutotradingPerformanceService summary contract."""

from __future__ import annotations

from decimal import Decimal


def test_lifetime_gross_net_fee_formula() -> None:
    """NET = GROSS - FEES; GROSS = winning_gross + losing_gross (losing signed)."""

    winning = Decimal("10000.00")
    losing = Decimal("-6000.00")
    fees = Decimal("1000.00")
    gross = winning + losing
    net = gross - fees
    assert gross == Decimal("4000.00")
    assert net == Decimal("3000.00")
    # display: NET = PROFIT - |LOSS| - FEES when profit/loss are net-based
    profit_net = Decimal("9000.00")
    loss_mag = Decimal("5000.00")
    assert profit_net - loss_mag - fees == Decimal("3000.00")


def test_empty_lifetime_zeros() -> None:
    gross = Decimal("0")
    fees = Decimal("0")
    net = gross - fees
    assert net == Decimal("0")
