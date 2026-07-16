from datetime import datetime, timezone
from types import SimpleNamespace
from decimal import Decimal
from stock_platform.broker.dispatcher import OrderDispatcher
from stock_platform.broker.models import BrokerOrderResult, BrokerOrderStatus
from stock_platform.order.models import OrderStatus

class FakeAdapter:
    def submit_order(self, request):
        return BrokerOrderResult(
            accepted=True,
            status=BrokerOrderStatus.ACCEPTED,
            broker_order_id="B001",
            submitted_at=datetime.now(timezone.utc),
        )

class FakeRepository:
    def __init__(self):
        self.entity = SimpleNamespace(
            order_id=1,
            client_order_id="ORD-1",
            account_id=1,
            exchange_code="KRX",
            symbol="005930",
            side_code="BUY",
            order_type_code="LIMIT",
            order_quantity=Decimal("1"),
            order_price=Decimal("70000"),
            time_in_force_code="DAY",
            status_code="CREATED",
            broker_order_id=None,
            reject_code=None,
            reject_message=None,
            failure_code=None,
            failure_message=None,
        )

    def get(self, *, order_id):
        return self.entity if order_id == 1 else None

    def change_status(self, *, entity, new_status, **kwargs):
        entity.status_code = new_status.value
        return entity

def test_dispatch_accepts_order():
    dispatcher = OrderDispatcher.__new__(OrderDispatcher)
    dispatcher.repository = FakeRepository()
    dispatcher.adapter = FakeAdapter()

    result = dispatcher.dispatch(1)

    assert result.status_code == OrderStatus.ACCEPTED.value
    assert result.broker_order_id == "B001"
