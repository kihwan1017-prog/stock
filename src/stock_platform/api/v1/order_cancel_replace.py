from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.account_ownership import (
    assert_order_resource_access,
)
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
from stock_platform.order.repository import TradingOrderRepository
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
    actor: str = Field(default="API", max_length=100)


class ReplaceOrderRequest(BaseModel):
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    actor: str = Field(default="API", max_length=100)


def _assert_order_owner(
    *,
    user: AuthenticatedUser,
    order_id: int,
    session: Session,
) -> None:
    entity = TradingOrderRepository(session).get(order_id)
    if entity is None:
        raise LookupError(f"Order not found: {order_id}")
    assert_order_resource_access(user, entity, session)


def _resolve_adapter_for_order(
    *,
    order_id: int,
    session: Session,
):
    entity = TradingOrderRepository(session).get(order_id)
    if entity is None:
        raise LookupError(f"Order not found: {order_id}")
    meta = entity.metadata_payload or {}
    environment = str(
        meta.get("environment") or "PAPER"
    ).upper()
    return resolve_broker_adapter_for_cancel(
        session,
        broker_code=entity.broker_code,
        environment=environment,
    )


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    request: CancelOrderRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    """주문 취소. LIVE는 이중 게이트 + transition 승인 시에만.
    Kill Switch 활성 시에도 취소는 허용(리스크 축소).
    """

    try:
        _assert_order_owner(
            user=user, order_id=order_id, session=session
        )
        adapter = _resolve_adapter_for_order(
            order_id=order_id,
            session=session,
        )
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
    """주문 정정. 업비트는 cancel+new로 어댑터가 처리."""

    try:
        _assert_order_owner(
            user=user, order_id=order_id, session=session
        )
        adapter = _resolve_adapter_for_order(
            order_id=order_id,
            session=session,
        )
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
