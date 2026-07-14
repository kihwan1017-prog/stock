import asyncio
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.realtime.dashboard_service import (
    RealtimeDashboardService,
)


class FakeSession:
    def execute(self, *args, **kwargs):
        return SimpleNamespace(
            scalar_one=lambda: 1
        )

    def rollback(self):
        pass


def test_database_status_up() -> None:
    service = RealtimeDashboardService.__new__(
        RealtimeDashboardService
    )
    service._session = FakeSession()

    result = service._database_status()

    assert result["status"] == "UP"
    assert result["result"] == 1


def test_account_summary_none_when_missing() -> None:
    class MissingAccountSession:
        def get(self, *args, **kwargs):
            return None

    service = RealtimeDashboardService.__new__(
        RealtimeDashboardService
    )
    service._session = MissingAccountSession()

    result = service._account_summary(
        account_id=999
    )

    assert result is None
