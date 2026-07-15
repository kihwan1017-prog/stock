from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class BacktestPerformanceInput:
    strategy_code: str
    market_code: str
    symbol: str | None
    period_start_date: date
    period_end_date: date
    parameter_payload: dict[str, Any]
    initial_capital: Decimal
    final_capital: Decimal
    total_trade_count: int
    winning_trade_count: int
    losing_trade_count: int
    gross_profit_amount: Decimal
    gross_loss_amount: Decimal
    maximum_drawdown_rate: Decimal
    annualized_return_rate: Decimal | None = None
    volatility_rate: Decimal | None = None
    sharpe_ratio: Decimal | None = None
    sortino_ratio: Decimal | None = None
    profit_factor: Decimal | None = None
    result_payload: dict[str, Any] | None = None
