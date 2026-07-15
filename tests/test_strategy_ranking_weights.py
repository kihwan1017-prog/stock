from decimal import Decimal

from stock_platform.performance.ranking_models import (
    StrategyRankingWeights,
)


def test_default_weights_sum_to_one() -> None:
    StrategyRankingWeights().validate()


def test_invalid_weights_are_rejected() -> None:
    weights = StrategyRankingWeights(
        return_rate=Decimal("0.50"),
        sharpe_ratio=Decimal("0.50"),
        sortino_ratio=Decimal("0.50"),
        win_rate=Decimal("0"),
        profit_factor=Decimal("0"),
        maximum_drawdown=Decimal("0"),
    )

    try:
        weights.validate()
    except ValueError as exc:
        assert "sum to 1.00" in str(exc)
    else:
        raise AssertionError(
            "ValueError was not raised"
        )
