from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.trading.models import (
    OrderSide,
    OrderType,
)
from stock_platform.trading.paper_engine import (
    PaperOrderValidationError,
)
from stock_platform.trading.repository import (
    PaperOrderRepository,
)
from stock_platform.trading.service import (
    PaperOrderService,
)


router = APIRouter(
    prefix="/api/v1/paper-orders",
    tags=["Paper Orders"],
)


class CreatePaperOrderRequest(BaseModel):
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    side: OrderSide
    order_type: OrderType
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = Field(default=None, gt=0)
    position_plan_id: int | None = Field(
        default=None,
        gt=0,
    )
    auto_accept: bool = True


class FillPaperOrderRequest(BaseModel):
    fill_quantity: Decimal = Field(gt=0)
    fill_price: Decimal = Field(gt=0)


class RejectPaperOrderRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _service(session: Session) -> PaperOrderService:
    return PaperOrderService(
        PaperOrderRepository(session)
    )


@router.post("")
def create_paper_order(
    request: CreatePaperOrderRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).create(
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            position_plan_id=request.position_plan_id,
            auto_accept=request.auto_accept,
        )
    except PaperOrderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{order_id}/fills")
def fill_paper_order(
    order_id: int,
    request: FillPaperOrderRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).fill(
            order_id=order_id,
            fill_quantity=request.fill_quantity,
            fill_price=request.fill_price,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperOrderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{order_id}/cancel")
def cancel_paper_order(
    order_id: int,
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).cancel(
            order_id=order_id
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperOrderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{order_id}/reject")
def reject_paper_order(
    order_id: int,
    request: RejectPaperOrderRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).reject(
            order_id=order_id,
            reason=request.reason,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperOrderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("")
def list_paper_orders(
    exchange_code: str | None = None,
    limit: int = 100,
    session: Session = Depends(get_db_session),
):
    rows = PaperOrderRepository(session).list_recent(
        exchange_code=exchange_code,
        limit=limit,
    )

    return rows
