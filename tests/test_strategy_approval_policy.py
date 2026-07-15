from decimal import Decimal

from stock_platform.strategy_deployment.policy_models import (
    StrategyApprovalPolicy,
)


def test_default_policy_values():
    policy = StrategyApprovalPolicy()

    assert policy.minimum_score == Decimal("0.60")
    assert policy.minimum_sharpe_ratio == Decimal(
        "0.80"
    )
    assert policy.maximum_drawdown_rate == Decimal(
        "0.20"
    )
    assert policy.minimum_trade_count == 20
