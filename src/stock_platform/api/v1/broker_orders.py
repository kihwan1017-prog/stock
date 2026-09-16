from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from stock_platform.api.deps_admin import require_admin


router = APIRouter(
    prefix="/api/v1/broker",
    tags=["Broker"],
    dependencies=[Depends(require_admin)],
)


class BrokerOrderApiRequest(BaseModel):
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    side: str
    order_type: str
    quantity: str | None = None
    price: str | None = None
    time_in_force: str = "DAY"
    approval_id: str | None = None
    approval_token: str | None = None


@router.post("/live-approval")
def issue_live_trading_approval():
    from stock_platform.broker.runtime import (
        live_trading_approval_service,
    )

    return live_trading_approval_service.issue()


@router.post("/orders")
async def place_broker_order(
    request: BrokerOrderApiRequest,
):
    """
    STEP8-2: Adapter 직행 주문 차단.
    Risk Engine + Kill Switch + Outbox 경로를 강제한다.
    """

    _ = request
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "POST /api/v1/broker/orders 직접 주문은 비활성입니다. "
            "POST /api/v1/order-execution/submit 를 사용하세요 "
            "(소유권 + ResolvedRiskPolicy + Risk Engine 필수)."
        ),
    )


@router.get("/orders/{broker_order_id}")
async def get_broker_order(
    broker_order_id: str,
):
    from stock_platform.broker.runtime import broker_order_adapter

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
    from stock_platform.broker.runtime import broker_order_adapter

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
    from stock_platform.broker.runtime import broker_order_adapter

    return await broker_order_adapter.get_account_snapshot()
