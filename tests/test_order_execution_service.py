from decimal import Decimal

from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.risk.engine import RiskManagementEngine


def test_resolve_size_uses_explicit_quantity() -> None:
    service = OrderExecutionService.__new__(OrderExecutionService)
    service._sizing_engine = RiskManagementEngine()

    quantity, price, plan = service._resolve_size(
        OrderExecutionCommand(
            account_id=1,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("3"),
            price=Decimal("70000"),
        )
    )
    assert quantity == Decimal("3")
    assert price == Decimal("70000")
    assert plan is None


def test_resolve_size_rejects_limit_without_price() -> None:
    service = OrderExecutionService.__new__(OrderExecutionService)
    service._sizing_engine = RiskManagementEngine()
    try:
        service._resolve_size(
            OrderExecutionCommand(
                account_id=1,
                broker_code="KIWOOM",
                exchange_code="KRX",
                symbol="005930",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                price=None,
            )
        )
        raised = False
    except ValueError:
        raised = True
    assert raised is True
