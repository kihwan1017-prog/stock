from datetime import date
from decimal import Decimal

from stock_platform.performance.backtest_mapper import (
    BacktestPerformanceMapper,
)
from stock_platform.performance.backtest_models import (
    BacktestPerformanceInput,
)


def test_calculates_derived_metrics() -> None:
    source = BacktestPerformanceInput(
        strategy_code="MA_CROSS",
        market_code="KRX",
        symbol="005930",
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
        parameter_payload={},
        initial_capital=Decimal("10000000"),
        final_capital=Decimal("11000000"),
        total_trade_count=10,
        winning_trade_count=6,
        losing_trade_count=4,
        gross_profit_amount=Decimal("1800000"),
        gross_loss_amount=Decimal("-800000"),
        maximum_drawdown_rate=Decimal("0.08"),
    )

    metrics = BacktestPerformanceMapper.to_metrics(
        source
    )

    assert metrics.total_return_rate == Decimal(
        "0.10"
    )
    assert metrics.win_rate == Decimal("0.6")
    assert metrics.average_profit_amount == Decimal(
        "300000"
    )
    assert metrics.average_loss_amount == Decimal(
        "-200000"
    )
    assert metrics.profit_factor == Decimal("2.25")
    assert metrics.net_profit_amount == Decimal(
        "1000000"
    )
