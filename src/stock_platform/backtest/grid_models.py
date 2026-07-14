from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class BacktestGridRequest:
    exchange_code: str
    symbol: str
    start_date: date
    end_date: date
    initial_capital: Decimal
    short_windows: list[int]
    long_windows: list[int]
    stop_loss_ratios: list[Decimal]
    take_profit_ratios: list[Decimal]
    position_ratios: list[Decimal]
    fee_ratio: Decimal
    sell_tax_ratio: Decimal
    slippage_ratio: Decimal
    top_n: int = 10


@dataclass(frozen=True, slots=True)
class BacktestGridItem:
    rank_no: int
    backtest_run_id: int
    short_window: int
    long_window: int
    stop_loss_ratio: Decimal
    take_profit_ratio: Decimal
    position_ratio: Decimal
    total_return_rate: Decimal
    maximum_drawdown_rate: Decimal
    win_rate: Decimal
    trade_count: int
    final_equity: Decimal
    score: Decimal


@dataclass(frozen=True, slots=True)
class BacktestGridResult:
    exchange_code: str
    symbol: str
    combination_count: int
    success_count: int
    failed_count: int
    top_results: list[BacktestGridItem]
    failures: list[dict]
