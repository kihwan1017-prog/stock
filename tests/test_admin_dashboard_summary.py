from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.admin_dashboard_summary_service import (
    AdminDashboardSummaryService,
)
from stock_platform.risk_engine.kill_switch_models import (
    KillSwitchState,
    KillSwitchStatus,
)


@pytest.mark.unit
def test_admin_dashboard_summary_kpis_without_account() -> None:
    session = MagicMock()
    session.get.return_value = None
    service = AdminDashboardSummaryService(session)
    kpis = service._build_kpis(account_id=999)
    assert kpis["valuation_mode"] == "unavailable"
    assert kpis["total_equity"] is None


@pytest.mark.unit
def test_admin_dashboard_summary_kpis_cost_basis() -> None:
    account = SimpleNamespace(
        account_id=1,
        available_cash=Decimal("10000000"),
        realized_profit_loss=Decimal("0"),
    )
    session = MagicMock()
    session.get.return_value = account
    session.scalars.return_value = []
    session.scalar.return_value = Decimal("0")

    service = AdminDashboardSummaryService(session)
    service._latest_close = lambda **kwargs: None  # type: ignore[method-assign]
    kpis = service._build_kpis(account_id=1)

    assert kpis["total_equity"] == "10000000.00"
    assert kpis["today_return_rate"] == "0.0000"
    assert kpis["unrealized_pnl"] == "0.00"
    assert kpis["realized_pnl"] == "0.00"
    assert kpis["open_position_count"] == 0


@pytest.mark.unit
def test_kill_switch_dict_includes_active() -> None:
    session = MagicMock()
    service = AdminDashboardSummaryService(session)

    class _FakeKill:
        def get_state(self):
            return KillSwitchState(
                status=KillSwitchStatus.INACTIVE,
                reason=None,
                activated_by=None,
                activated_at=None,
                deactivated_by=None,
                deactivated_at=None,
            )

    import stock_platform.operation.admin_dashboard_summary_service as mod

    original = mod.KillSwitchService
    mod.KillSwitchService = lambda _session: _FakeKill()  # type: ignore
    try:
        payload = service._kill_switch_dict()
    finally:
        mod.KillSwitchService = original

    assert payload["active"] is False
    assert payload["status"] == "INACTIVE"


def test_admin_dashboard_summary_route_registered() -> None:
    from stock_platform.api.main import app
    from stock_platform.api.router import (
        collect_duplicate_operation_ids,
    )

    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/dashboard/admin-summary" in paths
    assert collect_duplicate_operation_ids(app.router) == []
