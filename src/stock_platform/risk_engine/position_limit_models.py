from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PositionLimitPolicy:
    max_symbol_quantity: Decimal = Decimal("1000000")
    max_symbol_amount: Decimal = Decimal("500000")
    max_symbol_weight: Decimal = Decimal("0.25")
    max_total_invested_amount: Decimal = Decimal("5000000")
