from decimal import Decimal

from stock_platform.performance.models import (
    StrategyPerformanceMetrics,
)
from stock_platform.performance.service import (
    StrategyPerformanceService,
)


def test_validates_metrics() -> None:
    metrics = StrategyPerformanceMetrics(
        initial_capital=Decimal("10000000"),
        final_capital=Decimal("11000000"),
        total_return_rate=Decimal("0.10"),
        annualized_return_rate=Decimal("0.10"),
        maximum_drawdown_rate=Decimal("0.05"),
        volatility_rate=Decimal("0.12"),
        sharpe_ratio=Decimal("1.20"),
        sortino_ratio=Decimal("1.50"),
        win_rate=Decimal("0.60"),
        profit_factor=Decimal("1.80"),
        total_trade_count=10,
        winning_trade_count=6,
        losing_trade_count=4,
        average_profit_amount=Decimal("300000"),
        average_loss_amount=Decimal("-200000"),
        gross_profit_amount=Decimal("1800000"),
        gross_loss_amount=Decimal("-800000"),
        net_profit_amount=Decimal("1000000"),
    )

    StrategyPerformanceService._validate_metrics(
        metrics
    )


def test_rejects_invalid_trade_count() -> None:
    metrics = StrategyPerformanceMetrics(
        initial_capital=Decimal("10000000"),
        final_capital=Decimal("11000000"),
        total_return_rate=Decimal("0.10"),
        annualized_return_rate=None,
        maximum_drawdown_rate=Decimal("0.05"),
        volatility_rate=None,
        sharpe_ratio=None,
        sortino_ratio=None,
        win_rate=Decimal("0.60"),
        profit_factor=None,
        total_trade_count=5,
        winning_trade_count=4,
        losing_trade_count=3,
        average_profit_amount=Decimal("0"),
        average_loss_amount=Decimal("0"),
        gross_profit_amount=Decimal("0"),
        gross_loss_amount=Decimal("0"),
        net_profit_amount=Decimal("0"),
    )

    try:
        StrategyPerformanceService._validate_metrics(
            metrics
        )
    except ValueError as exc:
        assert "exceed total" in str(exc)
    else:
        raise AssertionError(
            "ValueError was not raised"
        )
