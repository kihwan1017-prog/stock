from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SimulationRequest:
    account_id: int
    exchange_code: str
    symbol: str
    trade_date: date
    slippage_ratio: Decimal = Decimal("0")
    fill_ratio: Decimal = Decimal("1")


@dataclass(frozen=True, slots=True)
class SimulatedFillResult:
    order_id: int
    account_id: int
    symbol: str
    side: str
    order_type: str
    requested_quantity: Decimal
    fill_quantity: Decimal
    reference_price: Decimal
    simulated_fill_price: Decimal
    order_status: str
    trade_id: int
