from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    window_no: int
    train_start_date: date
    train_end_date: date
    test_start_date: date
    test_end_date: date


@dataclass(frozen=True, slots=True)
class WalkForwardParameterSet:
    short_window: int
    long_window: int
    stop_loss_ratio: Decimal
    take_profit_ratio: Decimal
    position_ratio: Decimal


@dataclass(frozen=True, slots=True)
class WalkForwardWindowResult:
    window_no: int
    train_start_date: date
    train_end_date: date
    test_start_date: date
    test_end_date: date
    selected_parameters: WalkForwardParameterSet
    train_backtest_run_id: int
    test_backtest_run_id: int
    train_score: Decimal
    train_return_rate: Decimal
    train_maximum_drawdown_rate: Decimal
    test_return_rate: Decimal
    test_maximum_drawdown_rate: Decimal
    test_win_rate: Decimal
    test_trade_count: int


@dataclass(frozen=True, slots=True)
class WalkForwardSummary:
    window_count: int
    completed_window_count: int
    failed_window_count: int
    average_test_return_rate: Decimal
    compounded_test_return_rate: Decimal
    average_test_maximum_drawdown_rate: Decimal
    profitable_window_count: int
    profitable_window_rate: Decimal
    parameter_change_count: int


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    exchange_code: str
    symbol: str
    start_date: date
    end_date: date
    train_months: int
    test_months: int
    summary: WalkForwardSummary
    windows: list[WalkForwardWindowResult]
    failures: list[dict]
