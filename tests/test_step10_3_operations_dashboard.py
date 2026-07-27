"""STEP 10-3 — Operations Center Dashboard API 테스트 (Read-only)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from stock_platform.operation.operations_center_dashboard_service import (
    OperationsCenterDashboardService,
    clear_operations_center_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_operations_center_cache()
    yield
    clear_operations_center_cache()


def test_summary_read_only_flag() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.operation.operations_center_dashboard_service.OpsMonitoringDashboardService"
    ) as ops_cls:
        ops = ops_cls.return_value
        ops.overview.return_value = {
            "overall_status": "HEALTHY",
            "schedulers": {"recovery": {"actual_state": "RUNNING"}},
            "brokers": {"UPBIT": {"status": "HEALTHY"}},
            "runtime": {},
        }
        ops.schedulers.return_value = {"schedulers": []}
        ops.positions.return_value = {"positions": [], "count": 0}
        ops.audits.return_value = {"audits": [], "count": 0}
        ops.accounts.return_value = {"accounts": [], "count": 0}
        ops.runtimes.return_value = {"runtimes": []}
        with (
            patch(
                "stock_platform.trading.trading_scheduler_control_service.TradingSchedulerControlService"
            ) as ctrl_cls,
            patch(
                "stock_platform.operation.operations_center_dashboard_service.measure_db_latency_ms",
                return_value=("UP", 1.2, None),
            ),
            patch(
                "stock_platform.operation.operations_center_dashboard_service.migration_at_head",
                return_value=True,
            ),
            patch(
                "stock_platform.operation.operations_center_dashboard_service.KillSwitchService"
            ) as kill_cls,
        ):
            kill_cls.return_value.get_state.return_value.status = __import__(
                "stock_platform.risk_engine.kill_switch_models",
                fromlist=["KillSwitchStatus"],
            ).KillSwitchStatus.INACTIVE
            kill_cls.return_value.get_state.return_value.reason = None
            ctrl_cls.return_value.status.return_value = {
                "desired_state": "PAUSE",
                "actual_state": "PAUSED",
                "health": "PAUSED",
            }
            session.scalar.return_value = 0
            session.execute.return_value = []
            payload = OperationsCenterDashboardService(session).summary()
    assert payload["read_only"] is True
    assert "system" in payload
    assert "safety" in payload
    assert "audit" in payload


def test_summary_cache_hit() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.operation.operations_center_dashboard_service.OpsMonitoringDashboardService"
    ) as ops_cls:
        ops = ops_cls.return_value
        ops.overview.return_value = {
            "overall_status": "HEALTHY",
            "schedulers": {"recovery": {}},
            "brokers": {},
            "runtime": {},
        }
        ops.schedulers.return_value = {"schedulers": []}
        ops.positions.return_value = {"positions": [], "count": 0}
        ops.audits.return_value = {"audits": [], "count": 0}
        ops.accounts.return_value = {"accounts": [], "count": 0}
        ops.runtimes.return_value = {"runtimes": []}
        with (
            patch(
                "stock_platform.trading.trading_scheduler_control_service.TradingSchedulerControlService"
            ) as ctrl_cls,
            patch(
                "stock_platform.operation.operations_center_dashboard_service.measure_db_latency_ms",
                return_value=("UP", 1.0, None),
            ),
            patch(
                "stock_platform.operation.operations_center_dashboard_service.migration_at_head",
                return_value=True,
            ),
            patch(
                "stock_platform.operation.operations_center_dashboard_service.KillSwitchService"
            ) as kill_cls,
        ):
            from stock_platform.risk_engine.kill_switch_models import (
                KillSwitchStatus,
            )

            kill_cls.return_value.get_state.return_value.status = (
                KillSwitchStatus.INACTIVE
            )
            kill_cls.return_value.get_state.return_value.reason = None
            ctrl_cls.return_value.status.return_value = {
                "desired_state": "PAUSE",
                "actual_state": "PAUSED",
                "health": "PAUSED",
            }
            session.scalar.return_value = 0
            session.execute.return_value = []
            svc = OperationsCenterDashboardService(session)
            first = svc.summary(cache_ttl_sec=30)
            second = svc.summary(cache_ttl_sec=30)
    assert first["cache"]["hit"] is False
    assert second["cache"]["hit"] is True


def test_admin_dashboard_summary_route_requires_admin() -> None:
    from stock_platform.api.main import app

    client = TestClient(app)
    res = client.get("/api/v1/admin/dashboard/summary")
    assert res.status_code in {401, 403}
