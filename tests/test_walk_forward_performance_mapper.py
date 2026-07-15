from datetime import date
from decimal import Decimal

from stock_platform.performance.walk_forward_mapper import (
    WalkForwardPerformanceMapper,
)
from stock_platform.performance.walk_forward_models import (
    WalkForwardPerformanceInput,
    WalkForwardWindowPerformanceInput,
)


def test_maps_windows_and_aggregates() -> None:
    source = WalkForwardPerformanceInput(
        strategy_code="MA_CROSS_V1",
        market_code="KRX",
        symbol="005930",
        period_start_date=date(2023, 1, 1),
        period_end_date=date(2024, 12, 31),
        aggregate_parameter_payload={},
        windows=[
            WalkForwardWindowPerformanceInput(
                window_no=1,
                train_start_date=date(2023, 1, 1),
                train_end_date=date(2023, 12, 31),
                test_start_date=date(2024, 1, 1),
                test_end_date=date(2024, 3, 31),
                parameter_payload={"short": 5, "long": 20},
                result_payload={
                    "initial_capital": "10000000",
                    "final_capital": "10500000",
                    "total_trade_count": 10,
                    "winning_trade_count": 6,
                    "losing_trade_count": 4,
                    "gross_profit_amount": "900000",
                    "gross_loss_amount": "-400000",
                    "maximum_drawdown_rate": "0.05",
                },
            ),
            WalkForwardWindowPerformanceInput(
                window_no=2,
                train_start_date=date(2023, 4, 1),
                train_end_date=date(2024, 3, 31),
                test_start_date=date(2024, 4, 1),
                test_end_date=date(2024, 6, 30),
                parameter_payload={"short": 8, "long": 30},
                result_payload={
                    "initial_capital": "10000000",
                    "final_capital": "10300000",
                    "total_trade_count": 8,
                    "winning_trade_count": 5,
                    "losing_trade_count": 3,
                    "gross_profit_amount": "600000",
                    "gross_loss_amount": "-300000",
                    "maximum_drawdown_rate": "0.08",
                },
            ),
        ],
    )

    windows = (
        WalkForwardPerformanceMapper
        .to_window_entities(source)
    )
    metrics = (
        WalkForwardPerformanceMapper
        .aggregate_metrics(windows)
    )

    assert len(windows) == 2
    assert metrics.net_profit_amount == Decimal(
        "800000"
    )
    assert metrics.final_capital == Decimal(
        "10800000"
    )
    assert metrics.total_trade_count == 18
    assert metrics.maximum_drawdown_rate == Decimal(
        "0.08"
    )
