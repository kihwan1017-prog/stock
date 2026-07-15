from decimal import Decimal
from types import SimpleNamespace

from stock_platform.performance.ranking_service import (
    StrategyPerformanceRankingService,
)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def execute(self, statement):
        rows = [
            (
                SimpleNamespace(
                    strategy_code="A",
                    market_code="KRX",
                    symbol="005930",
                    run_type="BACKTEST",
                    strategy_performance_run_id=1,
                ),
                SimpleNamespace(
                    total_return_rate=Decimal("0.20"),
                    maximum_drawdown_rate=Decimal("0.10"),
                    sharpe_ratio=Decimal("1.5"),
                    sortino_ratio=Decimal("2.0"),
                    win_rate=Decimal("0.60"),
                    profit_factor=Decimal("1.8"),
                    total_trade_count=30,
                ),
            ),
            (
                SimpleNamespace(
                    strategy_code="B",
                    market_code="KRX",
                    symbol="005930",
                    run_type="BACKTEST",
                    strategy_performance_run_id=2,
                ),
                SimpleNamespace(
                    total_return_rate=Decimal("0.10"),
                    maximum_drawdown_rate=Decimal("0.20"),
                    sharpe_ratio=Decimal("0.8"),
                    sortino_ratio=Decimal("1.0"),
                    win_rate=Decimal("0.50"),
                    profit_factor=Decimal("1.2"),
                    total_trade_count=30,
                ),
            ),
        ]

        return FakeResult(rows)


def test_higher_quality_strategy_ranks_first() -> None:
    result = StrategyPerformanceRankingService(
        FakeSession()
    ).rank()

    assert result[0].rank == 1
    assert result[0].strategy_code == "A"
    assert result[0].score > result[1].score


def test_equal_values_scale_to_one() -> None:
    assert (
        StrategyPerformanceRankingService._scale(
            Decimal("1"),
            (Decimal("1"), Decimal("1")),
        )
        == Decimal("1")
    )
