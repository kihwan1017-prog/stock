from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.order.models import OrderStatus
from stock_platform.order.state_models import InvalidOrderStateTransition, OrderStateTransitionCommand
from stock_platform.order.state_service import OrderStateService

router = APIRouter(
    prefix='/api/v1/orders',
    tags=['Order States'],
    dependencies=[Depends(require_admin)],
)

class OrderStateTransitionRequest(BaseModel):
    target_status: OrderStatus
    actor: str = Field(default='API', min_length=1, max_length=100)
    reason_code: str | None = Field(default=None, max_length=100)
    message: str | None = None
    detail_payload: dict[str, Any] = {}

@router.post('/{order_id}/transition')
def transition_order_state(order_id: int, request: OrderStateTransitionRequest, session: Session = Depends(get_db_session)):
    try:
        return OrderStateService(session).transition(command=OrderStateTransitionCommand(
            order_id=order_id,
            target_status=request.target_status,
            actor=request.actor,
            reason_code=request.reason_code,
            message=request.message,
            detail_payload=request.detail_payload,
        ))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidOrderStateTransition as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

@router.get('/{order_id}/allowed-transitions')
def get_allowed_order_transitions(order_id: int, session: Session = Depends(get_db_session)):
    try:
        return {'order_id': order_id, 'allowed_transitions': OrderStateService(session).allowed_targets(order_id=order_id)}
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
