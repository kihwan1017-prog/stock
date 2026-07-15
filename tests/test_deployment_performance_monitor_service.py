from decimal import Decimal
from types import SimpleNamespace

from stock_platform.strategy_deployment.performance_monitor_models import (
    DeploymentPerformancePolicy,
    DeploymentPerformanceStatus,
)
from stock_platform.strategy_deployment.performance_monitor_service import (
    DeploymentPerformanceMonitorService,
)


class FakeCollector:
    def collect(self, **kwargs):
        return {
            "deployment": SimpleNamespace(
                strategy_deployment_id=1,
                strategy_code="TEST_V1",
                status_code="ACTIVE",
            ),
            "metric": SimpleNamespace(
                total_trade_count=10,
                total_return_rate=Decimal("0.05"),
                maximum_drawdown_rate=Decimal("0.04"),
                win_rate=Decimal("0.60"),
                profit_factor=Decimal("1.5"),
            ),
            "performance_run": object(),
            "consecutive_losses": 2,
        }


class FakeRepository:
    def save(self, snapshot):
        return snapshot


def test_healthy_performance():
    service = (
        DeploymentPerformanceMonitorService
        .__new__(
            DeploymentPerformanceMonitorService
        )
    )
    service._session = object()
    service._policy = DeploymentPerformancePolicy()
    service._collector = FakeCollector()
    service._repository = FakeRepository()

    result = service.check(
        deployment_id=1
    )

    assert result.status == (
        DeploymentPerformanceStatus.HEALTHY
    )
