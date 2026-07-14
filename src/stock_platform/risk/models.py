from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class PositionSizingMode(StrEnum):
    FIXED_AMOUNT = "FIXED_AMOUNT"
    FIXED_RATIO = "FIXED_RATIO"
    RISK_BASED = "RISK_BASED"


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    position_sizing_mode: PositionSizingMode
    fixed_amount: Decimal | None = None
    portfolio_ratio: Decimal | None = None
    risk_per_trade_ratio: Decimal = Decimal("0.01")
    stop_loss_ratio: Decimal = Decimal("0.03")
    take_profit_ratio: Decimal = Decimal("0.06")
    trailing_stop_ratio: Decimal | None = Decimal("0.03")
    maximum_position_ratio: Decimal = Decimal("0.20")
    maximum_positions: int = 5
    minimum_order_amount: Decimal = Decimal("10000")


@dataclass(frozen=True, slots=True)
class PositionSizingRequest:
    portfolio_value: Decimal
    available_cash: Decimal
    current_price: Decimal
    current_position_count: int
    policy: RiskPolicy


@dataclass(frozen=True, slots=True)
class PositionPlan:
    approved: bool
    reason: str
    quantity: Decimal
    order_amount: Decimal
    entry_price: Decimal
    stop_loss_price: Decimal
    take_profit_price: Decimal
    trailing_stop_ratio: Decimal | None
    maximum_loss_amount: Decimal


@dataclass(frozen=True, slots=True)
class ExitEvaluationRequest:
    entry_price: Decimal
    current_price: Decimal
    highest_price: Decimal
    stop_loss_price: Decimal
    take_profit_price: Decimal
    trailing_stop_ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class ExitDecision:
    should_exit: bool
    reason: str
    trigger_price: Decimal | None
