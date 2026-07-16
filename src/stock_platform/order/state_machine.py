from __future__ import annotations
from stock_platform.order.models import OrderStatus, TERMINAL_ORDER_STATUSES
from stock_platform.order.state_models import InvalidOrderStateTransition

class OrderStateMachine:
    _TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
        OrderStatus.CREATED: {OrderStatus.PENDING, OrderStatus.FAILED},
        OrderStatus.PENDING: {OrderStatus.SENT, OrderStatus.CANCEL_REQUESTED, OrderStatus.REJECTED, OrderStatus.FAILED},
        OrderStatus.SENT: {OrderStatus.ACCEPTED, OrderStatus.CANCEL_REQUESTED, OrderStatus.REJECTED, OrderStatus.FAILED},
        OrderStatus.ACCEPTED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCEL_REQUESTED, OrderStatus.REPLACE_REQUESTED, OrderStatus.REJECTED, OrderStatus.FAILED},
        OrderStatus.PARTIALLY_FILLED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCEL_REQUESTED, OrderStatus.REPLACE_REQUESTED, OrderStatus.FAILED},
        OrderStatus.CANCEL_REQUESTED: {OrderStatus.CANCELLED, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.FAILED},
        OrderStatus.REPLACE_REQUESTED: {OrderStatus.REPLACED, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCEL_REQUESTED, OrderStatus.FAILED},
        OrderStatus.FILLED: set(),
        OrderStatus.CANCELLED: set(),
        OrderStatus.REPLACED: set(),
        OrderStatus.REJECTED: set(),
        OrderStatus.FAILED: set(),
    }

    @classmethod
    def can_transition(cls, current: OrderStatus, target: OrderStatus) -> bool:
        return target in cls._TRANSITIONS.get(current, set())

    @classmethod
    def validate_transition(cls, *, current: OrderStatus, target: OrderStatus) -> None:
        if current in TERMINAL_ORDER_STATUSES or not cls.can_transition(current, target):
            raise InvalidOrderStateTransition(current=current, target=target)

    @classmethod
    def transition(cls, *, current: OrderStatus, target: OrderStatus) -> OrderStatus:
        cls.validate_transition(current=current, target=target)
        return target

    @classmethod
    def allowed_targets(cls, current: OrderStatus) -> set[OrderStatus]:
        return set(cls._TRANSITIONS.get(current, set()))
