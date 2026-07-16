from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.order.state_machine import OrderStateMachine
from stock_platform.order.state_models import OrderStateTransitionCommand, OrderStateTransitionResult

class OrderStateService:
    def __init__(self, session: Session) -> None:
        self._repository = TradingOrderRepository(session)

    def transition(self, *, command: OrderStateTransitionCommand) -> OrderStateTransitionResult:
        entity = self._repository.get(order_id=command.order_id)
        if entity is None:
            raise LookupError('Order not found')
        current = OrderStatus(entity.status_code)
        OrderStateMachine.validate_transition(current=current, target=command.target_status)
        updated = self._repository.change_status(
            entity=entity,
            new_status=command.target_status,
            actor=command.actor,
            reason_code=command.reason_code,
            message=command.message,
            detail_payload=command.detail_payload or {},
            validate_transition=False,
        )
        return OrderStateTransitionResult(
            order_id=updated.order_id,
            previous_status=current,
            current_status=OrderStatus(updated.status_code),
            changed_at=datetime.now(timezone.utc),
        )

    def allowed_targets(self, *, order_id: int) -> list[str]:
        entity = self._repository.get(order_id=order_id)
        if entity is None:
            raise LookupError('Order not found')
        current = OrderStatus(entity.status_code)
        return sorted(status.value for status in OrderStateMachine.allowed_targets(current))
