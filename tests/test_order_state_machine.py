import pytest
from stock_platform.order.models import OrderStatus
from stock_platform.order.state_machine import OrderStateMachine
from stock_platform.order.state_models import InvalidOrderStateTransition

@pytest.mark.parametrize(('current','target'), [
    (OrderStatus.CREATED, OrderStatus.PENDING),
    (OrderStatus.PENDING, OrderStatus.SENT),
    (OrderStatus.SENT, OrderStatus.ACCEPTED),
    (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED),
    (OrderStatus.ACCEPTED, OrderStatus.FILLED),
    (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED),
    (OrderStatus.ACCEPTED, OrderStatus.CANCEL_REQUESTED),
    (OrderStatus.CANCEL_REQUESTED, OrderStatus.CANCELLED),
    (OrderStatus.ACCEPTED, OrderStatus.REPLACE_REQUESTED),
    (OrderStatus.REPLACE_REQUESTED, OrderStatus.REPLACED),
])
def test_valid_transitions(current, target):
    assert OrderStateMachine.can_transition(current, target)
    assert OrderStateMachine.transition(current=current, target=target) == target

@pytest.mark.parametrize(('current','target'), [
    (OrderStatus.CREATED, OrderStatus.FILLED),
    (OrderStatus.PENDING, OrderStatus.ACCEPTED),
    (OrderStatus.CANCELLED, OrderStatus.ACCEPTED),
    (OrderStatus.FILLED, OrderStatus.CANCEL_REQUESTED),
    (OrderStatus.REPLACED, OrderStatus.PENDING),
    (OrderStatus.REJECTED, OrderStatus.PENDING),
    (OrderStatus.FAILED, OrderStatus.PENDING),
])
def test_invalid_transitions(current, target):
    assert not OrderStateMachine.can_transition(current, target)
    with pytest.raises(InvalidOrderStateTransition):
        OrderStateMachine.transition(current=current, target=target)
