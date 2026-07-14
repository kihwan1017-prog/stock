from decimal import Decimal
from types import SimpleNamespace

from stock_platform.backtest.comparison_service import (
    BacktestComparisonService,
)


class FakeRepository:
    def list_runs(self, **kwargs):
        return [
            SimpleNamespace(
                backtest_run_id=1,
                strategy_code="MOVING_AVERAGE_CROSS",
                exchange_code="KRX",
                symbol="005930",
                total_return_rate=Decimal("20"),
                maximum_drawdown_rate=Decimal("10"),
                win_rate=Decimal("50"),
                trade_count=10,
                final_equity=Decimal("12000000"),
                parameters={"short_window": 5},
            ),
            SimpleNamespace(
                backtest_run_id=2,
                strategy_code="MOVING_AVERAGE_CROSS",
                exchange_code="KRX",
                symbol="005930",
                total_return_rate=Decimal("18"),
                maximum_drawdown_rate=Decimal("5"),
                win_rate=Decimal("60"),
                trade_count=8,
                final_equity=Decimal("11800000"),
                parameters={"short_window": 10},
            ),
        ]


def test_compare_ranks_by_score() -> None:
    service = BacktestComparisonService.__new__(
        BacktestComparisonService
    )
    service._repository = FakeRepository()

    result = service.compare(
        exchange_code="KRX",
        symbol="005930",
    )

    assert result[0].backtest_run_id == 2
    assert result[0].rank_no == 1
    assert result[1].backtest_run_id == 1
