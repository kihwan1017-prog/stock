from sqlalchemy.orm import Session
from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.exceptions import BrokerError
from stock_platform.broker.models import BrokerOrderRequest
from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import TradingOrderRepository

class OrderDispatcher:
    def __init__(self, session: Session, adapter: BrokerAdapter) -> None:
        self.repository = TradingOrderRepository(session)
        self.adapter = adapter

    def dispatch(self, order_id: int, actor: str = "ORDER_DISPATCHER"):
        entity = self.repository.get(order_id=order_id)
        if entity is None:
            raise LookupError("Order not found")

        self.repository.change_status(
            entity=entity,
            new_status=OrderStatus.PENDING,
            actor=actor,
            reason_code="DISPATCH_REQUESTED",
        )

        entity = self.repository.get(order_id=order_id)
        self.repository.change_status(
            entity=entity,
            new_status=OrderStatus.SENT,
            actor=actor,
            reason_code="BROKER_REQUEST_SENT",
        )

        request = BrokerOrderRequest(
            client_order_id=entity.client_order_id,
            account_id=entity.account_id,
            exchange_code=entity.exchange_code,
            symbol=entity.symbol,
            side=entity.side_code,
            order_type=entity.order_type_code,
            quantity=entity.order_quantity,
            price=entity.order_price,
            time_in_force=entity.time_in_force_code,
        )

        try:
            result = self.adapter.submit_order(request)
        except BrokerError as exc:
            entity = self.repository.get(order_id=order_id)
            entity.failure_code = exc.__class__.__name__
            entity.failure_message = str(exc)
            return self.repository.change_status(
                entity=entity,
                new_status=OrderStatus.FAILED,
                actor=actor,
                reason_code="BROKER_ERROR",
                message=str(exc),
            )
        except Exception as exc:
            entity = self.repository.get(order_id=order_id)
            entity.failure_code = "UNEXPECTED_BROKER_ERROR"
            entity.failure_message = str(exc)
            return self.repository.change_status(
                entity=entity,
                new_status=OrderStatus.FAILED,
                actor=actor,
                reason_code="UNEXPECTED_BROKER_ERROR",
                message=str(exc),
            )

        entity = self.repository.get(order_id=order_id)
        entity.broker_order_id = result.broker_order_id

        if result.accepted:
            return self.repository.change_status(
                entity=entity,
                new_status=OrderStatus.ACCEPTED,
                actor=actor,
                reason_code="BROKER_ACCEPTED",
            )

        entity.reject_code = result.reject_code
        entity.reject_message = result.reject_message
        return self.repository.change_status(
            entity=entity,
            new_status=OrderStatus.REJECTED,
            actor=actor,
            reason_code=result.reject_code or "BROKER_REJECTED",
            message=result.reject_message,
        )
