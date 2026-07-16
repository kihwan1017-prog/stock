from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from stock_platform.database.session import get_db_session
from stock_platform.order.models import CreateOrderCommand, OrderSide, OrderTimeInForce, OrderType
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.order.service import TradingOrderService

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

@router.post("", status_code=status.HTTP_201_CREATED)
def create_order(request: CreateOrderRequest, session: Session = Depends(get_db_session)):
    try:
        return TradingOrderService(session).create(
            CreateOrderCommand(
                account_id=request.account_id,
                broker_code=request.broker_code,
                exchange_code=request.exchange_code,
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                price=request.price,
                time_in_force=request.time_in_force,
                strategy_code=request.strategy_code,
                strategy_deployment_id=request.strategy_deployment_id,
                portfolio_id=request.portfolio_id,
                position_id=request.position_id,
                client_order_id=request.client_order_id,
                metadata_payload=request.metadata_payload,
            ),
            request.actor,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/{order_id}")
def get_order(order_id: int, session: Session = Depends(get_db_session)):
    entity = TradingOrderRepository(session).get(order_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return entity

@router.get("/{order_id}/history")
def get_order_history(order_id: int, session: Session = Depends(get_db_session)):
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
    session: Session = Depends(get_db_session),
):
    return TradingOrderRepository(session).list(
        account_id, status_code, exchange_code, symbol, limit, offset
    )
