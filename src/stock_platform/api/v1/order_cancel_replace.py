from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.adapter import (
    KiwoomBrokerAdapter,
)
from stock_platform.database.session import (
    get_db_session,
)
from stock_platform.order.cancel_replace_service import (
    OrderCancelReplaceService,
)


router = APIRouter(
    prefix="/api/v1/orders",
    tags=["Order Cancel Replace"],
)


class CancelOrderRequest(BaseModel):
    quantity: Decimal | None = Field(
        default=None,
        gt=0,
    )
    actor: str = "API"


class ReplaceOrderRequest(BaseModel):
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    actor: str = "API"


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    request: CancelOrderRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return OrderCancelReplaceService(
            session=session,
            adapter=KiwoomBrokerAdapter(),
        ).cancel(
            order_id=order_id,
            quantity=request.quantity,
            actor=request.actor,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@router.post("/{order_id}/replace")
def replace_order(
    order_id: int,
    request: ReplaceOrderRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return OrderCancelReplaceService(
            session=session,
            adapter=KiwoomBrokerAdapter(),
        ).replace(
            order_id=order_id,
            quantity=request.quantity,
            price=request.price,
            actor=request.actor,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
