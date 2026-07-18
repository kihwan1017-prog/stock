from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any


class RiskDecisionLevel(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCK = "BLOCK"


class RiskOrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    max_order_amount: Decimal = Decimal("100000")
    max_order_quantity: Decimal = Decimal("1000000")
    max_open_positions: int = 5
    max_investment_ratio: Decimal = Decimal("0.70")
    max_daily_loss: Decimal = Decimal("300000")
    trading_start_time: time = time(9, 0)
    trading_end_time: time = time(15, 20)
    enforce_krx_market_hours: bool = True
    emergency_stop_enabled: bool = False
    allow_sell_during_emergency_stop: bool = True
    max_market_data_age_seconds: int = 30
    max_broker_error_rate: Decimal = Decimal("0.5")
    block_on_stale_market_data: bool = True
    block_on_broker_unstable: bool = True


@dataclass(frozen=True, slots=True)
class RiskOrderRequest:
    exchange_code: str
    symbol: str
    side: RiskOrderSide
    quantity: Decimal
    price: Decimal
    account_id: int
    requested_at: datetime
    market_data_age_seconds: int | None = None
    broker_error_rate: Decimal | None = None

    @property
    def order_amount(self) -> Decimal:
        return self.quantity * self.price


@dataclass(frozen=True, slots=True)
class RiskAccountState:
    cash_balance: Decimal
    total_asset_value: Decimal
    invested_amount: Decimal
    daily_realized_profit_loss: Decimal
    daily_unrealized_profit_loss: Decimal
    open_position_count: int
    symbol_position_quantity: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class RiskRuleResult:
    rule_code: str
    level: RiskDecisionLevel
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RiskEvaluationResult:
    decision: RiskDecisionLevel
    allowed: bool
    evaluated_at: datetime
    order_amount: Decimal
    results: list[RiskRuleResult]
