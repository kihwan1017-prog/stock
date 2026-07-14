from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class RebalancingFrequency(StrEnum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMIANNUAL = "SEMIANNUAL"
    YEARLY = "YEARLY"


@dataclass(frozen=True, slots=True)
class RebalancingAsset:
    exchange_code: str
    symbol: str
    target_weight: Decimal


@dataclass(frozen=True, slots=True)
class RebalancingTrade:
    trade_date: date
    exchange_code: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    gross_amount: Decimal
    fee_amount: Decimal
    tax_amount: Decimal
    slippage_amount: Decimal


@dataclass(frozen=True, slots=True)
class RebalancingSnapshot:
    trade_date: date
    cash: Decimal
    position_value: Decimal
    total_equity: Decimal
    rebalance_executed: bool


@dataclass(frozen=True, slots=True)
class RebalancingSummary:
    initial_capital: Decimal
    final_equity: Decimal
    total_profit_loss: Decimal
    total_return_rate: Decimal
    cagr: Decimal
    maximum_drawdown_rate: Decimal
    annualized_volatility: Decimal
    sharpe_ratio: Decimal
    sortino_ratio: Decimal
    calmar_ratio: Decimal
    trade_count: int
    rebalance_count: int


@dataclass(frozen=True, slots=True)
class RebalancingBacktestResult:
    start_date: date
    end_date: date
    frequency: RebalancingFrequency
    summary: RebalancingSummary
    trades: list[RebalancingTrade]
    snapshots: list[RebalancingSnapshot]
    final_weights: dict[str, Decimal]
