from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from stock_platform.broker.dispatcher import OrderDispatcher
from stock_platform.database.session import get_db_session

router = APIRouter(prefix="/api/v1/orders", tags=["Order Dispatch"])


class DispatchOrderRequest(BaseModel):
    actor: str = "API"


@router.post("/{order_id}/dispatch")
def dispatch_order(
    order_id: int,
    request: DispatchOrderRequest,
    session: Session = Depends(get_db_session),
):
    """기존 주문을 Outbox에 적재한다 (Broker 직접 호출 금지)."""
    try:
        return OrderDispatcher(session).dispatch(
            order_id,
            request.actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
