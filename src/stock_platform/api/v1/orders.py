from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.order.models import OrderSide, OrderTimeInForce, OrderType
from stock_platform.order.repository import TradingOrderRepository

router = APIRouter(prefix="/api/v1/orders", tags=["Orders"])


class CreateOrderRequest(BaseModel):
    account_id: int = Field(gt=0)
    broker_code: str
    exchange_code: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = None
    time_in_force: OrderTimeInForce = OrderTimeInForce.DAY
    strategy_code: str | None = None
    strategy_deployment_id: int | None = None
    portfolio_id: int | None = None
    position_id: int | None = None
    client_order_id: str | None = None
    metadata_payload: dict[str, Any] = {}
    actor: str = "API"


@router.post("", status_code=status.HTTP_400_BAD_REQUEST)
def create_order(
    request: CreateOrderRequest,
    _: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    """가드 없는 직접 생성은 차단 — order-execution/submit 사용."""

    _ = (request, session)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "직접 주문 생성은 비활성입니다. "
            "POST /api/v1/order-execution/submit 를 사용하세요 "
            "(Risk + Kill Switch 필수)."
        ),
    )


@router.get("/{order_id}")
def get_order(
    order_id: int,
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    entity = TradingOrderRepository(session).get(order_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return entity


@router.get("/{order_id}/history")
def get_order_history(
    order_id: int,
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    repo = TradingOrderRepository(session)
    if repo.get(order_id) is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return repo.history(order_id)


@router.get("")
def list_orders(
    account_id: int | None = None,
    status_code: str | None = None,
    exchange_code: str | None = None,
    symbol: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    return TradingOrderRepository(session).list(
        account_id,
        status_code,
        exchange_code,
        symbol,
        limit,
        offset,
    )
