from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import (
    get_db_session,
)
from stock_platform.order.cancel_replace_service import (
    OrderCancelReplaceService,
)
from stock_platform.order.trading_guards import (
    TradingGuardError,
    resolve_broker_adapter_for_cancel,
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
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    """
    주문 취소.
    실거래 어댑터는 KIWOOM_LIVE_ORDER_ENABLED + transition 승인 시에만.
    """

    try:
        adapter = resolve_broker_adapter_for_cancel(session)
        return OrderCancelReplaceService(
            session=session,
            adapter=adapter,
        ).cancel(
            order_id=order_id,
            quantity=request.quantity,
            actor=request.actor or user.username,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except (ValueError, TradingGuardError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@router.post("/{order_id}/replace")
def replace_order(
    order_id: int,
    request: ReplaceOrderRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    """
    주문 정정.
    실거래 어댑터는 KIWOOM_LIVE_ORDER_ENABLED + transition 승인 시에만.
    """

    try:
        adapter = resolve_broker_adapter_for_cancel(session)
        return OrderCancelReplaceService(
            session=session,
            adapter=adapter,
        ).replace(
            order_id=order_id,
            quantity=request.quantity,
            price=request.price,
            actor=request.actor or user.username,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except (ValueError, TradingGuardError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
