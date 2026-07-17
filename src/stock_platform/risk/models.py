from dataclasses import dataclass
from decimal import Decimal

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
