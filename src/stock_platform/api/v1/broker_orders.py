from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from stock_platform.api.deps_admin import require_admin
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderType,
)
from stock_platform.broker.runtime import (
    broker_order_adapter,
    broker_order_service,
    live_trading_approval_service,
)


router = APIRouter(
    prefix="/api/v1/broker",
    tags=["Broker"],
    dependencies=[Depends(require_admin)],
)


class BrokerOrderApiRequest(BaseModel):
    exchange_code: str = Field(
        min_length=1,
        max_length=20,
    )
    symbol: str = Field(
        min_length=1,
        max_length=30,
    )
    side: BrokerOrderSide
    order_type: BrokerOrderType
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = Field(
        default=None,
        gt=0,
    )
    time_in_force: str = Field(
        default="DAY",
        min_length=1,
        max_length=20,
    )
    approval_id: str | None = None
    approval_token: str | None = None


@router.post("/live-approval")
def issue_live_trading_approval():
    return live_trading_approval_service.issue()


@router.post("/orders")
async def place_broker_order(
    request: BrokerOrderApiRequest,
):
    if (
        request.order_type == BrokerOrderType.LIMIT
        and request.price is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="price is required for LIMIT order",
        )

    if (
        request.order_type == BrokerOrderType.MARKET
        and request.price is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="price must not be provided for MARKET order",
        )

    try:
        broker_request = BrokerOrderRequest(
            client_order_id=str(uuid.uuid4()),
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            time_in_force=request.time_in_force,
        )

        return await broker_order_service.place_order(
            request=broker_request,
            approval_id=request.approval_id,
            approval_token=request.approval_token,
        )

    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/orders/{broker_order_id}")
async def get_broker_order(
    broker_order_id: str,
):
    try:
        return await broker_order_adapter.get_order(
            broker_order_id,
        )

    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/orders/{broker_order_id}/cancel")
async def cancel_broker_order(
    broker_order_id: str,
):
    try:
        return await broker_order_adapter.cancel_order(
            broker_order_id,
        )

    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/account")
async def get_broker_account():
    return await broker_order_adapter.get_account_snapshot()
