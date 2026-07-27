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
        **_kwargs,
    ) -> BrokerOrderResult:
        # 재시도 시 동일 client_order_id → 동일 broker_order_id (중복 실주문 방지)
        stable = "".join(
            ch for ch in request.client_order_id.upper() if ch.isalnum()
        )
        if len(stable) < 8:
            stable = f"{stable}{uuid4().hex}".upper()
        broker_order_id = f"PAPER-{stable[:16]}"
        return BrokerOrderResult(
            accepted=True,
            status=BrokerOrderStatus.ACCEPTED,
            broker_order_id=broker_order_id,
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
