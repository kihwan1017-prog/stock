from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.risk_engine.dashboard_service import (
    RiskDashboardService,
)


def test_position_summary_by_uba() -> None:
    service = RiskDashboardService(MagicMock())
    account = SimpleNamespace(
        available_order_amount=Decimal("1000000"),
    )
    positions = [
        SimpleNamespace(
            evaluation_amount=Decimal("500000"),
            quantity=Decimal("5"),
            snapshot_status="ACTIVE",
        ),
        SimpleNamespace(
            evaluation_amount=Decimal("300000"),
            quantity=Decimal("3"),
            snapshot_status="ACTIVE",
        ),
    ]
    service._session = MagicMock()
    # get_active_by_uba monkeypatch via repository import path
    from stock_platform.broker import account_repository as repo_mod

    original = repo_mod.BrokerAccountSnapshotRepository

    class FakeRepo:
        def __init__(self, session):
            pass

        def get_active_by_uba(self, uba_id):
            assert uba_id == 7
            return account, positions

    repo_mod.BrokerAccountSnapshotRepository = FakeRepo
    try:
        summary = service._position_summary_by_uba(
            user_broker_account_id=7
        )
    finally:
        repo_mod.BrokerAccountSnapshotRepository = original

    assert summary is not None
    assert summary.cash_balance == Decimal("1000000")
    assert summary.invested_amount == Decimal("800000")
    assert summary.total_asset_value == Decimal("1800000")
    assert summary.open_position_count == 2
