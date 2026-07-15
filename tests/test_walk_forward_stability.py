from decimal import Decimal
from types import SimpleNamespace

from stock_platform.performance.walk_forward_stability import (
    WalkForwardStabilityAnalyzer,
)


def test_analyzes_window_stability() -> None:
    windows = [
        SimpleNamespace(
            total_return_rate=Decimal("0.10"),
            maximum_drawdown_rate=Decimal("0.05"),
        ),
        SimpleNamespace(
            total_return_rate=Decimal("0.04"),
            maximum_drawdown_rate=Decimal("0.08"),
        ),
        SimpleNamespace(
            total_return_rate=Decimal("-0.02"),
            maximum_drawdown_rate=Decimal("0.12"),
        ),
    ]

    result = WalkForwardStabilityAnalyzer.analyze(
        windows
    )

    assert result["window_count"] == 3
    assert result["positive_window_count"] == 2
    assert result["negative_window_count"] == 1
    assert result["best_window_return_rate"] == "0.10"
    assert result["worst_window_return_rate"] == "-0.02"
