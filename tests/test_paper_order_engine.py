from decimal import Decimal

from stock_platform.trading.models import (
    OrderSide,
    OrderStatus,
    OrderType,
)
from stock_platform.trading.paper_engine import (
    PaperOrderEngine,
)


def test_create_and_fill_market_order() -> None:
    engine = PaperOrderEngine()

    order = engine.create_order(
        exchange_code="KRX",
        symbol="005930",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
        price=None,
    )

    engine.accept(order)
    engine.fill(
        order,
        fill_quantity=Decimal("4"),
        fill_price=Decimal("70000"),
    )

    assert order.status_code == (
        OrderStatus.PARTIALLY_FILLED.value
    )
    assert order.filled_quantity == Decimal("4")

    engine.fill(
        order,
        fill_quantity=Decimal("6"),
        fill_price=Decimal("71000"),
    )

    assert order.status_code == OrderStatus.FILLED.value
    assert order.filled_quantity == Decimal("10")
    assert order.average_fill_price == Decimal(
        "70600.00000000"
    )


def test_cancel_order() -> None:
    engine = PaperOrderEngine()

    order = engine.create_order(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.01"),
        price=Decimal("100000000"),
    )

    engine.accept(order)
    engine.cancel(order)

    assert order.status_code == (
        OrderStatus.CANCELLED.value
    )
