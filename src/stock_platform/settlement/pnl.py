"""STEP 8-5-16 — Decimal 비교·PnL 유틸."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def d(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def within_tolerance(
    left: Decimal, right: Decimal, *, tolerance: Decimal
) -> bool:
    return abs(left - right) <= tolerance


@dataclass(frozen=True, slots=True)
class PnLBreakdown:
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    fees: Decimal
    taxes: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    opening_equity: Decimal | None
    closing_equity: Decimal | None
    deposits_unknown: bool


def compute_pnl(
    *,
    realized_pnl: Decimal,
    unrealized_pnl: Decimal,
    fees: Decimal,
    taxes: Decimal,
    opening_equity: Decimal | None,
    closing_equity: Decimal | None,
    net_deposit_withdrawal: Decimal | None = None,
) -> PnLBreakdown:
    gross = realized_pnl + unrealized_pnl
    net = realized_pnl - fees - taxes
    deposits_unknown = net_deposit_withdrawal is None
    return PnLBreakdown(
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        fees=fees,
        taxes=taxes,
        gross_pnl=gross,
        net_pnl=net,
        opening_equity=opening_equity,
        closing_equity=closing_equity,
        deposits_unknown=deposits_unknown,
    )
