from datetime import datetime, timezone
from types import SimpleNamespace

from stock_platform.strategy_deployment.dashboard_service import (
    StrategyOperationsDashboardService,
)


def test_deployment_to_dict():
    item = SimpleNamespace(
        strategy_deployment_id=1,
        strategy_code="MA_CROSS_V1",
        strategy_performance_run_id=10,
        market_code="KRX",
        symbol="005930",
        mode_code="PAPER",
        status_code="ACTIVE",
        parameter_payload={"short": 5},
        requested_by="tester",
        activated_at=datetime.now(timezone.utc),
        stopped_at=None,
        replaced_by_deployment_id=None,
        error_message=None,
        created_at=datetime.now(timezone.utc),
    )

    result = (
        StrategyOperationsDashboardService
        ._deployment_to_dict(item)
    )

    assert result["strategy_code"] == "MA_CROSS_V1"
    assert result["status_code"] == "ACTIVE"
    assert result["mode_code"] == "PAPER"
