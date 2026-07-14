from decimal import Decimal
from types import SimpleNamespace

from stock_platform.trading.execution_service import (
    PaperExecutionService,
)


class FakeSession:
    def rollback(self):
        self.rolled_back = True


class FakeOrderRepository:
    def __init__(self):
        self.order = SimpleNamespace(
            order_id=1,
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            status_code="ACCEPTED",
            requested_quantity=Decimal("10"),
            filled_quantity=Decimal("0"),
            average_fill_price=None,
        )

    def get(self, order_id: int):
        return self.order if order_id == 1 else None


class FakeAccountRepository:
    def __init__(self):
        self.account = SimpleNamespace(
            account_id=1,
            available_cash=Decimal("1000000"),
            realized_profit_loss=Decimal("0"),
        )

    def get_account(self, account_id: int):
        return self.account if account_id == 1 else None


class FakeOrderService:
    def __init__(self, repository):
        self.repository = repository

    def fill(
        self,
        *,
        order_id: int,
        fill_quantity: Decimal,
        fill_price: Decimal,
    ):
        order = self.repository.get(order_id)
        order.filled_quantity += fill_quantity
        order.average_fill_price = fill_price
        order.status_code = (
            "FILLED"
            if order.filled_quantity
            == order.requested_quantity
            else "PARTIALLY_FILLED"
        )
        return order


class FakeAccountService:
    def __init__(self, repository):
        self.repository = repository

    def apply_fill(self, **kwargs):
        account = self.repository.get_account(
            kwargs["account_id"]
        )
        trade_amount = (
            kwargs["quantity"]
            * kwargs["fill_price"]
        )
        account.available_cash -= trade_amount

        return SimpleNamespace(
            trade_id=10,
            trade_amount=trade_amount,
            realized_profit_loss=Decimal("0"),
        )


def test_applies_fill_to_order_and_account() -> None:
    service = PaperExecutionService.__new__(
        PaperExecutionService
    )
    service._session = FakeSession()
    service._order_repository = FakeOrderRepository()
    service._account_repository = FakeAccountRepository()
    service._order_service = FakeOrderService(
        service._order_repository
    )
    service._account_service = FakeAccountService(
        service._account_repository
    )

    result = service.apply_fill(
        account_id=1,
        order_id=1,
        fill_quantity=Decimal("10"),
        fill_price=Decimal("50000"),
    )

    assert result.order_status == "FILLED"
    assert result.order_filled_quantity == Decimal("10")
    assert result.account_available_cash == Decimal("500000")
    assert result.trade_id == 10
