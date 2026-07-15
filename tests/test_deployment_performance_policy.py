from decimal import Decimal

from stock_platform.strategy_deployment.performance_monitor_models import (
    DeploymentPerformancePolicy,
)


def test_default_monitor_policy():
    policy = DeploymentPerformancePolicy()

    assert policy.minimum_trade_count == 5
    assert policy.minimum_total_return_rate == Decimal(
        "-0.03"
    )
    assert policy.maximum_drawdown_rate == Decimal(
        "0.10"
    )
    assert policy.auto_stop_enabled is False
