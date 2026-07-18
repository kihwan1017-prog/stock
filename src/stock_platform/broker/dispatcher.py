from sqlalchemy.orm import Session

from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.order.execution_service import OrderExecutionService
from stock_platform.order.repository import TradingOrderRepository


class OrderDispatcher:
    """
    호환용 디스패처.

    Broker를 직접 호출하지 않고 OrderExecutionService → Outbox로 위임한다.
    """

    def __init__(
        self,
        session: Session,
        adapter: BrokerAdapter | None = None,
    ) -> None:
        # adapter는 하위 호환을 위해 받지만 사용하지 않는다.
        self._session = session
        self._adapter = adapter
        self._execution_service = OrderExecutionService(session)
        self._repository = TradingOrderRepository(session)

    def dispatch(self, order_id: int, actor: str = "ORDER_DISPATCHER"):
        result = self._execution_service.enqueue_existing(
            order_id=order_id,
            actor=actor,
        )
        entity = self._repository.get(order_id)
        if entity is None:
            raise LookupError("Order not found")
        return {
            "order_id": entity.order_id,
            "client_order_id": entity.client_order_id,
            "status_code": entity.status_code,
            "outbox_id": result.outbox_id,
            "reason_code": result.reason_code,
            "broker_order_id": entity.broker_order_id,
        }
