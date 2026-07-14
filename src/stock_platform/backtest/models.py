from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class BacktestSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class BacktestPrice:
    trade_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class BacktestSignal:
    trade_date: date
    side: BacktestSide
    price: Decimal
    quantity: Decimal
    reason: str


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    entry_date: date
    exit_date: date
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    gross_profit_loss: Decimal
    fee_amount: Decimal
    tax_amount: Decimal
    net_profit_loss: Decimal
    return_rate: Decimal
    entry_reason: str
    exit_reason: str


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    initial_capital: Decimal
    final_equity: Decimal
    total_return_rate: Decimal
    maximum_drawdown_rate: Decimal
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: Decimal
    total_profit_loss: Decimal
    average_trade_return_rate: Decimal


@dataclass(frozen=True, slots=True)
class BacktestResult:
    exchange_code: str
    symbol: str
    start_date: date
    end_date: date
    summary: BacktestSummary
    trades: list[BacktestTrade]
    equity_curve: list[tuple[date, Decimal]]
