from decimal import Decimal
from types import SimpleNamespace

from stock_platform.risk_engine.dashboard_service import (
    RiskDashboardService,
)


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self):
        self.account = SimpleNamespace(
            available_order_amount=Decimal(
                "1000000"
            )
        )
        self.positions = [
            SimpleNamespace(
                evaluation_amount=Decimal("500000"),
                quantity=Decimal("5"),
            ),
            SimpleNamespace(
                evaluation_amount=Decimal("300000"),
                quantity=Decimal("3"),
            ),
        ]

    def scalar(self, statement):
        return self.account

    def scalars(self, statement):
        return FakeScalars(self.positions)


def test_position_summary() -> None:
    service = RiskDashboardService(
        FakeSession()
    )

    summary = service._position_summary(
        account_number="123"
    )

    assert summary is not None
    assert summary.cash_balance == Decimal(
        "1000000"
    )
    assert summary.invested_amount == Decimal(
        "800000"
    )
    assert summary.total_asset_value == Decimal(
        "1800000"
    )
    assert summary.open_position_count == 2
