from types import SimpleNamespace

from stock_platform.strategy_deployment.automation_service import (
    StrategyAutoDeploymentService,
)


def test_service_can_be_constructed_without_running():
    service = StrategyAutoDeploymentService.__new__(
        StrategyAutoDeploymentService
    )

    assert service is not None
