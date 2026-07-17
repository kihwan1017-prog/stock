from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.broker.models import (
    BrokerOrderResult,
    BrokerOrderStatus,
)
from stock_platform.order.outbox_dispatcher import (
    OrderOutboxDispatcher,
)


class Adapter:
    def submit_order(self, request):
        assert request.symbol == "005930"
        return BrokerOrderResult(
            accepted=True,
            status=BrokerOrderStatus.ACCEPTED,
            broker_order_id="100",
            submitted_at=datetime.now(timezone.utc),
        )


def test_submit_dispatch():
    result = OrderOutboxDispatcher(
        Adapter()
    ).dispatch(
        event_type="SUBMIT_ORDER",
        idempotency_key="SUBMIT-1",
        payload={
            "client_order_id": "CLIENT-1",
            "account_id": 1,
            "exchange_code": "KRX",
            "symbol": "005930",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": "1",
            "price": "70000",
            "time_in_force": "DAY",
        },
    )

    assert result["accepted"] is True
    assert result["broker_order_id"] == "100"
