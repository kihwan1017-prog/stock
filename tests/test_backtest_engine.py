from datetime import date, timedelta
from decimal import Decimal

from stock_platform.backtest.engine import BacktestEngine
from stock_platform.backtest.models import BacktestPrice
from stock_platform.backtest.strategy import (
    MovingAverageCrossStrategy,
    MovingAverageStrategyConfig,
)


def _prices() -> list[BacktestPrice]:
    values = [
        100, 99, 98, 97, 96,
        95, 94, 93, 92, 91,
        92, 93, 94, 95, 96,
        97, 98, 99, 100, 101,
        102, 103, 104, 105, 106,
        107, 108, 109, 110, 111,
    ]

    start = date(2026, 1, 1)

    return [
        BacktestPrice(
            trade_date=start + timedelta(days=index),
            open_price=Decimal(str(value)),
            high_price=Decimal(str(value + 1)),
            low_price=Decimal(str(value - 1)),
            close_price=Decimal(str(value)),
            volume=Decimal("1000"),
        )
        for index, value in enumerate(values)
    ]


def test_backtest_runs_and_returns_summary() -> None:
    strategy = MovingAverageCrossStrategy(
        MovingAverageStrategyConfig(
            short_window=3,
            long_window=5,
            stop_loss_ratio=Decimal("0.05"),
            take_profit_ratio=Decimal("0.10"),
            position_ratio=Decimal("0.50"),
        )
    )

    result = BacktestEngine(strategy).run(
        exchange_code="KRX",
        symbol="005930",
        prices=_prices(),
        initial_capital=Decimal("1000000"),
        fee_ratio=Decimal("0"),
        sell_tax_ratio=Decimal("0"),
        slippage_ratio=Decimal("0"),
    )

    assert result.summary.initial_capital == Decimal(
        "1000000"
    )
    assert result.summary.final_equity > 0
    assert result.summary.trade_count >= 1
    assert len(result.equity_curve) == len(_prices())
