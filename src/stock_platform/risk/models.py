from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_order_amount: Decimal
    max_position_amount: Decimal
    max_daily_loss: Decimal
    max_open_positions: int


@dataclass(frozen=True, slots=True)
class RiskRequest:
    order_amount: Decimal
    current_position_amount: Decimal
    daily_realized_pnl: Decimal
    open_positions: int
    creates_new_position: bool


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reasons: tuple[str, ...]


class PositionSizingMode(str, Enum):
    FIXED_AMOUNT = "FIXED_AMOUNT"
    FIXED_RATIO = "FIXED_RATIO"
    RISK_BASED = "RISK_BASED"


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    position_sizing_mode: PositionSizingMode
    risk_per_trade_ratio: Decimal
    stop_loss_ratio: Decimal
    take_profit_ratio: Decimal
    maximum_position_ratio: Decimal
    maximum_positions: int
    minimum_order_amount: Decimal
    fixed_amount: Decimal | None = None
    portfolio_ratio: Decimal | None = None
    trailing_stop_ratio: Decimal | None = None
    maximum_total_invested_ratio: Decimal = Decimal("1")


@dataclass(frozen=True, slots=True)
class PositionSizingRequest:
    portfolio_value: Decimal
    available_cash: Decimal
    current_price: Decimal
    current_position_count: int
    policy: RiskPolicy
    stop_price: Decimal | None = None
    invested_amount: Decimal = Decimal("0")
    apply_krx_lot_rounding: bool = True


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
    trailing_stop_ratio: Decimal | None = None
    # 진입가 대비 상대 손실 비율 (예: 0.08 = -8%)
    relative_loss_ratio: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ExitDecision:
    should_exit: bool
    reason: str
    trigger_price: Decimal | None = None