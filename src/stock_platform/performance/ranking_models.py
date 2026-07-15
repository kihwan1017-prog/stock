from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class StrategyRankingWeights:
    return_rate: Decimal = Decimal("0.30")
    sharpe_ratio: Decimal = Decimal("0.20")
    sortino_ratio: Decimal = Decimal("0.10")
    win_rate: Decimal = Decimal("0.15")
    profit_factor: Decimal = Decimal("0.10")
    maximum_drawdown: Decimal = Decimal("0.15")

    def validate(self) -> None:
        values = [
            self.return_rate,
            self.sharpe_ratio,
            self.sortino_ratio,
            self.win_rate,
            self.profit_factor,
            self.maximum_drawdown,
        ]

        if any(value < 0 for value in values):
            raise ValueError(
                "ranking weights must not be negative"
            )

        total = sum(values, Decimal("0"))

        if total != Decimal("1.00"):
            raise ValueError(
                "ranking weights must sum to 1.00"
            )


@dataclass(frozen=True, slots=True)
class StrategyRankingItem:
    rank: int
    strategy_code: str
    market_code: str
    symbol: str | None
    run_type: str
    score: Decimal
    total_return_rate: Decimal
    maximum_drawdown_rate: Decimal
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    win_rate: Decimal
    profit_factor: Decimal | None
    total_trade_count: int
    strategy_performance_run_id: int
