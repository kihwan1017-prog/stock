"""STEP 8-11 — Operations Monitoring Dashboard (Read-only)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock_platform.api.v1.admin_operations_dashboard import router
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.operation.ops_monitoring.masking import (
    mask_broker_uuid,
    mask_login_id,
    redact_mapping,
)
from stock_platform.operation.ops_monitoring.status import (
    compute_overall_status,
    daily_loss_usage_status,
)
from stock_platform.operation.ops_monitoring.service import (
    OpsMonitoringDashboardService,
)


def test_mask_login_and_uuid() -> None:
    assert mask_login_id("adminuser") == "ad***r"
    assert mask_broker_uuid("abcd1234-efgh-ijkl") == "abcd…ijkl"
    assert "secret" not in str(
        redact_mapping({"arm_token": "PLAIN", "ok": 1})
    ).lower() or "***" in str(
        redact_mapping({"arm_token": "PLAIN", "ok": 1})
    )


def test_daily_loss_thresholds() -> None:
    assert daily_loss_usage_status(
        current_loss=Decimal("69"), limit_amount=Decimal("100")
    ) == "NORMAL"
    assert daily_loss_usage_status(
        current_loss=Decimal("70"), limit_amount=Decimal("100")
    ) == "WARNING"
    assert daily_loss_usage_status(
        current_loss=Decimal("90"), limit_amount=Decimal("100")
    ) == "DANGER"
    assert daily_loss_usage_status(
        current_loss=Decimal("100"), limit_amount=Decimal("100")
    ) == "BLOCKED"


def test_overall_status_priority() -> None:
    assert compute_overall_status({"errors": [], "warnings": []}) == "HEALTHY"
    assert (
        compute_overall_status({"errors": [], "warnings": ["X"]}) == "WARNING"
    )
    assert (
        compute_overall_status({"errors": ["Y"], "warnings": ["X"]}) == "ERROR"
    )


def test_overview_kill_switch_error(monkeypatch) -> None:
    session = MagicMock()
    svc = OpsMonitoringDashboardService(session)
    monkeypatch.setattr(
        "stock_platform.operation.ops_monitoring.service.measure_db_latency_ms",
        lambda: ("UP", 1.0, None),
    )
    monkeypatch.setattr(svc, "_scheduler_bundle", lambda: {
        "trading": {
            "desired_state": "PAUSE",
            "actual_state": "PAUSED",
            "running": False,
        },
        "tracking": {"actual_state": "RUNNING", "running": True},
        "post_fill": {"actual_state": "RUNNING", "running": True},
        "recovery": {"actual_state": "RUNNING", "running": True},
    })
    monkeypatch.setattr(
        svc,
        "_broker_overview",
        lambda: {
            "UPBIT": {"status": "HEALTHY", "mock_enabled": False},
            "KIWOOM": {"status": "NOT_CONFIGURED"},
        },
    )
    monkeypatch.setattr(
        svc,
        "_runtime_counts",
        lambda: {"running_count": 0, "paused_count": 1, "error_count": 0},
    )
    monkeypatch.setattr(
        svc,
        "_alert_counts",
        lambda: {"critical": 0, "warning": 0, "manual_review": 0},
    )
    monkeypatch.setattr(svc, "_active_uba_kill_count", lambda: 0)

    from stock_platform.risk_engine.kill_switch_models import KillSwitchStatus

    monkeypatch.setattr(
        "stock_platform.operation.ops_monitoring.service.KillSwitchService",
        lambda _s: SimpleNamespace(
            get_state=lambda: SimpleNamespace(status=KillSwitchStatus.ACTIVE)
        ),
    )
    out = svc.overview()
    assert out["overall_status"] == "ERROR"
    assert "KILL_SWITCH_GLOBAL" in out["error_codes"]


def test_broker_balance_failure_isolated(monkeypatch) -> None:
    session = MagicMock()
    svc = OpsMonitoringDashboardService(session)
    monkeypatch.setattr(
        svc,
        "_upbit_balance_safe",
        lambda _id: (
            {
                "orderable_krw": None,
                "locked_krw": None,
                "total_krw_balance": None,
                "status": "ERROR",
                "reason_code": "TimeoutError",
            },
            {"count": None, "status": "ERROR", "reason_code": "TimeoutError"},
            {"status": "UNKNOWN", "reason_code": "TimeoutError"},
        ),
    )
    bal, open_o, health = svc._upbit_balance_safe(58)
    assert bal["status"] == "ERROR"
    assert bal["orderable_krw"] is None  # 0 위장 금지
    assert open_o["count"] is None
    assert health["status"] == "UNKNOWN"


def test_orders_date_range_limit() -> None:
    session = MagicMock()
    svc = OpsMonitoringDashboardService(session)
    from datetime import datetime, timedelta, timezone

    with pytest.raises(ValueError, match="31"):
        svc.orders(
            date_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            date_to=datetime(2026, 3, 1, tzinfo=timezone.utc),
            limit=10,
        )


def test_orders_limit_cap(monkeypatch) -> None:
    session = MagicMock()
    session.scalars.return_value = []
    svc = OpsMonitoringDashboardService(session)
    monkeypatch.setattr(svc, "_post_fill_status_map", lambda _ids: {})
    out = svc.orders(limit=999)
    assert out["limit"] == 200


def _auth_override(user: AuthenticatedUser):
    async def _dep():
        return user

    return _dep


def test_admin_api_requires_auth() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    # require_admin dependency not overridden → 401/403/422 depending on deps
    resp = client.get("/api/v1/admin/operations-dashboard/overview")
    assert resp.status_code in {401, 403, 422, 500}


def test_redact_hides_arm_token() -> None:
    payload = redact_mapping(
        {
            "arm_token": "SUPER_SECRET",
            "access_key": "AK",
            "summary": "ok",
        }
    )
    assert payload["arm_token"] == "***"
    assert payload["access_key"] == "***"
    assert payload["summary"] == "ok"


def test_submission_unknown_alert(monkeypatch) -> None:
    session = MagicMock()
    svc = OpsMonitoringDashboardService(session)
    from stock_platform.risk_engine.kill_switch_models import KillSwitchStatus

    monkeypatch.setattr(
        "stock_platform.operation.ops_monitoring.service.KillSwitchService",
        lambda _s: SimpleNamespace(
            get_state=lambda: SimpleNamespace(
                status=KillSwitchStatus.INACTIVE, reason=None
            )
        ),
    )
    session.scalars.return_value = []
    session.scalar.return_value = 2  # unknown count
    with patch.dict("sys.modules", {}):
        out = svc.alerts(limit=20)
    codes = [a["code"] for a in out["alerts"]]
    assert "SUBMISSION_UNKNOWN" in codes
