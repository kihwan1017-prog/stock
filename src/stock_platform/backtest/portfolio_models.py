from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

@dataclass(frozen=True, slots=True)
class PortfolioBacktestAsset:
    exchange_code: str
    symbol: str
    weight: Decimal

@dataclass(frozen=True, slots=True)
class PortfolioBacktestAssetResult:
    exchange_code: str
    symbol: str
    weight: Decimal
    allocated_capital: Decimal
    final_equity: Decimal
    total_profit_loss: Decimal
    total_return_rate: Decimal
    maximum_drawdown_rate: Decimal
    trade_count: int
    win_rate: Decimal

@dataclass(frozen=True, slots=True)
class PortfolioBacktestSummary:
    initial_capital: Decimal
    invested_capital: Decimal
    unallocated_capital: Decimal
    final_equity: Decimal
    total_profit_loss: Decimal
    total_return_rate: Decimal
    maximum_drawdown_rate: Decimal
    profitable_asset_count: int
    losing_asset_count: int
    asset_count: int

@dataclass(frozen=True, slots=True)
class PortfolioBacktestResult:
    start_date: date
    end_date: date
    summary: PortfolioBacktestSummary
    assets: list[PortfolioBacktestAssetResult]
    equity_curve: list[tuple[date, Decimal]]
    failures: list[dict]
