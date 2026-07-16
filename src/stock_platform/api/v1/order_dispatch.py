from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from stock_platform.broker.dispatcher import OrderDispatcher
from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.database.session import get_db_session

router = APIRouter(prefix="/api/v1/orders", tags=["Order Dispatch"])

class DispatchOrderRequest(BaseModel):
    environment: BrokerEnvironment = BrokerEnvironment.PAPER
    broker_code: str = "KIWOOM"
    actor: str = "API"

@router.post("/{order_id}/dispatch")
def dispatch_order(
    order_id: int,
    request: DispatchOrderRequest,
    session: Session = Depends(get_db_session),
):
    try:
        adapter = BrokerAdapterFactory.create(request.environment, request.broker_code)
        return OrderDispatcher(session, adapter).dispatch(order_id, request.actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
