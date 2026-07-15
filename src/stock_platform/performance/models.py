from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class PerformanceRunType(StrEnum):
    BACKTEST = "BACKTEST"
    WALK_FORWARD = "WALK_FORWARD"
    PAPER = "PAPER"
    LIVE = "LIVE"


class PerformanceRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class StrategyPerformanceMetrics:
    initial_capital: Decimal
    final_capital: Decimal
    total_return_rate: Decimal
    annualized_return_rate: Decimal | None
    maximum_drawdown_rate: Decimal
    volatility_rate: Decimal | None
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    win_rate: Decimal
    profit_factor: Decimal | None
    total_trade_count: int
    winning_trade_count: int
    losing_trade_count: int
    average_profit_amount: Decimal
    average_loss_amount: Decimal
    gross_profit_amount: Decimal
    gross_loss_amount: Decimal
    net_profit_amount: Decimal


@dataclass(frozen=True, slots=True)
class StrategyPerformanceRunResult:
    strategy_code: str
    run_type: PerformanceRunType
    market_code: str
    symbol: str | None
    period_start_date: date
    period_end_date: date
    metrics: StrategyPerformanceMetrics
    parameter_payload: dict[str, Any]
    result_payload: dict[str, Any]
    completed_at: datetime
