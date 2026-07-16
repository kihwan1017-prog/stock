from decimal import Decimal
from stock_platform.order.models import CreateOrderCommand, OrderSide, OrderType
from stock_platform.order.service import TradingOrderService

def command(price=Decimal("72000"), quantity=Decimal("1")):
    return CreateOrderCommand(
        account_id=1, broker_code="KIWOOM", exchange_code="KRX",
        symbol="005930", side=OrderSide.BUY, order_type=OrderType.LIMIT,
        quantity=quantity, price=price,
    )

def test_valid_limit_order():
    TradingOrderService._validate(command())

def test_limit_requires_price():
    try:
        TradingOrderService._validate(command(price=None))
    except ValueError as exc:
        assert "requires price" in str(exc)
    else:
        raise AssertionError("ValueError was not raised")

def test_quantity_positive():
    try:
        TradingOrderService._validate(command(quantity=Decimal("0")))
    except ValueError as exc:
        assert "quantity" in str(exc)
    else:
        raise AssertionError("ValueError was not raised")
