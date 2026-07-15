from datetime import datetime, timezone
from types import SimpleNamespace

from stock_platform.strategy_deployment.models import (
    StrategyDeploymentMode,
    StrategyDeploymentRequest,
    StrategyDeploymentStatus,
)
from stock_platform.strategy_deployment.service import (
    PaperStrategyDeploymentService,
)


class FakeValidator:
    def validate_performance_run(self, **kwargs):
        return SimpleNamespace(status_code="COMPLETED")


class FakeRepository:
    def __init__(self):
        self.current = None
        self.history = []

    def get_active(self, **kwargs):
        return self.current

    def create(self, **kwargs):
        return SimpleNamespace(
            strategy_deployment_id=2,
            strategy_code=kwargs["strategy_code"],
            strategy_performance_run_id=(
                kwargs["strategy_performance_run_id"]
            ),
            mode_code=kwargs["mode_code"],
            status_code="PENDING",
            activated_at=None,
            stopped_at=None,
            error_message=None,
        )

    def add_history(self, **kwargs):
        self.history.append(kwargs)


class FakeSession:
    def commit(self):
        pass

    def refresh(self, entity):
        pass

    def rollback(self):
        pass


def test_deploys_paper_strategy() -> None:
    service = PaperStrategyDeploymentService.__new__(
        PaperStrategyDeploymentService
    )
    service._session = FakeSession()
    service._validator = FakeValidator()
    service._repository = FakeRepository()

    result = service.deploy(
        StrategyDeploymentRequest(
            strategy_code="MA_CROSS_V1",
            strategy_performance_run_id=10,
            market_code="KRX",
            symbol="005930",
            mode=StrategyDeploymentMode.PAPER,
            parameter_payload={"short": 5},
            requested_by="tester",
        )
    )

    assert result.status == (
        StrategyDeploymentStatus.ACTIVE
    )
    assert result.strategy_code == "MA_CROSS_V1"
