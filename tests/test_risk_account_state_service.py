from decimal import Decimal
from types import SimpleNamespace

from stock_platform.risk_engine.account_state_service import (
    RiskAccountStateService,
)


class FakeScalars:
    def __iter__(self):
        return iter(
            [
                SimpleNamespace(
                    exchange_code="KRX",
                    symbol="005930",
                    quantity=Decimal("10"),
                    evaluation_amount=Decimal("720000"),
                    profit_loss=Decimal("20000"),
                ),
                SimpleNamespace(
                    exchange_code="KRX",
                    symbol="000660",
                    quantity=Decimal("5"),
                    evaluation_amount=Decimal("900000"),
                    profit_loss=Decimal("-10000"),
                ),
            ]
        )


class FakeSession:
    def scalar(self, statement):
        return SimpleNamespace(
            deposit_amount=Decimal("1000000"),
            available_order_amount=Decimal("800000"),
            total_profit_loss=Decimal("10000"),
        )

    def scalars(self, statement):
        return FakeScalars()


def test_builds_risk_account_state() -> None:
    service = RiskAccountStateService(
        FakeSession()
    )

    state = service.load(
        broker_code="KIWOOM",
        account_number="123",
        exchange_code="KRX",
        symbol="005930",
    )

    assert state.cash_balance == Decimal("800000")
    assert state.invested_amount == Decimal("1620000")
    assert state.total_asset_value == Decimal("2620000")
    assert state.open_position_count == 2
    assert state.symbol_position_quantity == Decimal("10")
