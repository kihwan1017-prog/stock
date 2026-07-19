from datetime import datetime, timezone
from uuid import uuid4

from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerOrderStatus,
)


class PaperBrokerAdapter(BrokerAdapter):
    def submit_order(
        self,
        request: BrokerOrderRequest,
    ) -> BrokerOrderResult:
        return BrokerOrderResult(
            accepted=True,
            status=BrokerOrderStatus.ACCEPTED,
            broker_order_id=f"PAPER-{uuid4().hex[:12].upper()}",
            submitted_at=datetime.now(timezone.utc),
        )

    def cancel_order(
        self,
        broker_order_id: str,
        **_kwargs,
    ) -> BrokerOrderResult:
        # OutboxDispatcher가 exchange/symbol/qty kwargs를 넘김
        return BrokerOrderResult(
            True,
            BrokerOrderStatus.ACCEPTED,
            broker_order_id,
            datetime.now(timezone.utc),
        )

    def replace_order(
        self,
        broker_order_id: str,
        request: BrokerOrderRequest,
        **_kwargs,
    ) -> BrokerOrderResult:
        _ = request
        return BrokerOrderResult(
            True,
            BrokerOrderStatus.ACCEPTED,
            broker_order_id,
            datetime.now(timezone.utc),
        )

    def get_order(
        self,
        broker_order_id: str,
    ) -> BrokerOrderResult:
        return BrokerOrderResult(
            True,
            BrokerOrderStatus.ACCEPTED,
            broker_order_id,
            datetime.now(timezone.utc),
        )
