from decimal import Decimal
from unittest.mock import MagicMock

from stock_platform.broker.dispatcher import OrderDispatcher
from stock_platform.order.execution_service import OrderExecutionResult


def test_order_dispatcher_enqueues_via_execution_service():
    dispatcher = OrderDispatcher.__new__(OrderDispatcher)
    fake_service = MagicMock()
    fake_service.enqueue_existing.return_value = (
        OrderExecutionResult(
            allowed=True,
            reason_code="QUEUED",
            order_id=1,
            outbox_id=9,
            status_code="PENDING",
            client_order_id="ORD-1",
            quantity=Decimal("1"),
            price=Decimal("70000"),
        )
    )
    fake_repo = MagicMock()
    fake_repo.get.return_value = MagicMock(
        order_id=1,
        client_order_id="ORD-1",
        status_code="PENDING",
        broker_order_id=None,
    )
    dispatcher._execution_service = fake_service
    dispatcher._repository = fake_repo

    result = dispatcher.dispatch(1)

    fake_service.enqueue_existing.assert_called_once_with(
        order_id=1,
        actor="ORDER_DISPATCHER",
    )
    assert result["status_code"] == "PENDING"
    assert result["outbox_id"] == 9
    assert result["reason_code"] == "QUEUED"
