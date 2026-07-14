from decimal import Decimal
from types import SimpleNamespace

from stock_platform.trading.account_models import (
    PaperAccount,
)
from stock_platform.trading.account_service import (
    PaperAccountService,
)
from stock_platform.trading.models import OrderSide


class FakeRepository:
    def __init__(self) -> None:
        self.account = PaperAccount(
            account_name="테스트",
            currency_code="KRW",
            initial_cash=Decimal("1000000"),
            available_cash=Decimal("1000000"),
            realized_profit_loss=Decimal("0"),
        )
        self.account.account_id = 1
        self.position = None
        self.trade_id = 0

    def save_account(self, account):
        account.account_id = 1
        self.account = account
        return account

    def get_account(self, account_id):
        return self.account if account_id == 1 else None

    def get_position(self, **kwargs):
        return self.position

    def save_position(self, position):
        if getattr(position, "position_id", None) is None:
            position.position_id = 1
        self.position = position
        return position

    def save_trade(self, trade):
        self.trade_id += 1
        trade.trade_id = self.trade_id
        return trade

    def list_positions(self, *, account_id):
        if self.position is None:
            return []
        if self.position.quantity <= 0:
            return []
        return [self.position]

    def commit(self):
        return None


def test_buy_and_sell_updates_cash_and_profit() -> None:
    repository = FakeRepository()
    service = PaperAccountService(repository)  # type: ignore[arg-type]

    service.apply_fill(
        account_id=1,
        exchange_code="KRX",
        symbol="005930",
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        fill_price=Decimal("50000"),
    )

    assert repository.account.available_cash == Decimal(
        "500000.00"
    )
    assert repository.position.quantity == Decimal("10")
    assert repository.position.average_entry_price == Decimal(
        "50000.00000000"
    )

    trade = service.apply_fill(
        account_id=1,
        exchange_code="KRX",
        symbol="005930",
        side=OrderSide.SELL,
        quantity=Decimal("4"),
        fill_price=Decimal("55000"),
    )

    assert trade.realized_profit_loss == Decimal(
        "20000.00"
    )
    assert repository.account.available_cash == Decimal(
        "720000.00"
    )
    assert repository.account.realized_profit_loss == Decimal(
        "20000.00"
    )
    assert repository.position.quantity == Decimal("6")


def test_account_valuation() -> None:
    repository = FakeRepository()
    service = PaperAccountService(repository)  # type: ignore[arg-type]

    service.apply_fill(
        account_id=1,
        exchange_code="KRX",
        symbol="005930",
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        fill_price=Decimal("50000"),
    )

    valuation = service.value_account(
        account_id=1,
        prices={
            "KRX:005930": Decimal("55000"),
        },
    )

    assert valuation.position_market_value == Decimal(
        "550000.00"
    )
    assert valuation.unrealized_profit_loss == Decimal(
        "50000.00"
    )
    assert valuation.total_equity == Decimal(
        "1050000.00"
    )
