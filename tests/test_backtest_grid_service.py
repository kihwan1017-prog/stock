from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.backtest.grid_models import (
    BacktestGridRequest,
)
from stock_platform.backtest.grid_service import (
    BacktestGridService,
)


class FakePersistence:
    def __init__(self) -> None:
        self.run_id = 0

    def run_and_save_moving_average(self, **kwargs):
        self.run_id += 1

        short_window = kwargs["short_window"]
        long_window = kwargs["long_window"]

        return_rate = Decimal(
            str(30 - short_window)
        )
        drawdown = Decimal(
            str(long_window / 10)
        )
        win_rate = Decimal("50")

        run = SimpleNamespace(
            backtest_run_id=self.run_id
        )
        summary = SimpleNamespace(
            total_return_rate=return_rate,
            maximum_drawdown_rate=drawdown,
            win_rate=win_rate,
            trade_count=10,
            final_equity=Decimal("12000000"),
        )
        result = SimpleNamespace(summary=summary)

        return run, result


def test_grid_runs_combinations_and_ranks() -> None:
    service = BacktestGridService.__new__(
        BacktestGridService
    )
    service._persistence = FakePersistence()

    result = service.run(
        BacktestGridRequest(
            exchange_code="KRX",
            symbol="005930",
            start_date=date(2023, 1, 1),
            end_date=date(2026, 7, 14),
            initial_capital=Decimal("10000000"),
            short_windows=[5, 10],
            long_windows=[20, 60],
            stop_loss_ratios=[
                Decimal("0.03"),
            ],
            take_profit_ratios=[
                Decimal("0.10"),
            ],
            position_ratios=[
                Decimal("0.20"),
            ],
            fee_ratio=Decimal("0.00015"),
            sell_tax_ratio=Decimal("0.0018"),
            slippage_ratio=Decimal("0.001"),
            top_n=3,
        )
    )

    assert result.combination_count == 4
    assert result.success_count == 4
    assert result.failed_count == 0
    assert len(result.top_results) == 3
    assert result.top_results[0].rank_no == 1


def test_invalid_window_combination_is_recorded() -> None:
    service = BacktestGridService.__new__(
        BacktestGridService
    )
    service._persistence = FakePersistence()

    result = service.run(
        BacktestGridRequest(
            exchange_code="KRX",
            symbol="005930",
            start_date=date(2023, 1, 1),
            end_date=date(2026, 7, 14),
            initial_capital=Decimal("10000000"),
            short_windows=[20],
            long_windows=[10],
            stop_loss_ratios=[
                Decimal("0.03"),
            ],
            take_profit_ratios=[
                Decimal("0.10"),
            ],
            position_ratios=[
                Decimal("0.20"),
            ],
            fee_ratio=Decimal("0.00015"),
            sell_tax_ratio=Decimal("0.0018"),
            slippage_ratio=Decimal("0.001"),
            top_n=3,
        )
    )

    assert result.success_count == 0
    assert result.failed_count == 1
