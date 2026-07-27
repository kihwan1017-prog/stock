from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.broker.kiwoom.pending_factory import (
    build_kiwoom_pending_order_client,
)
from stock_platform.broker.kiwoom.pending_service import (
    KiwoomPendingOrderService,
)
from stock_platform.broker.pending_repository import BrokerPendingOrderRepository
from stock_platform.trading.account_identity import AccountIdentityError

router = APIRouter(
    prefix="/api/v1/broker/kiwoom/pending-orders",
    tags=["Kiwoom Pending Orders"],
    dependencies=[Depends(require_admin)],
)


class ModifyOrderRequest(BaseModel):
    symbol: str = Field(min_length=1)
    quantity: str = Field(min_length=1)
    price: str = Field(min_length=1)
    trade_type: str = Field(min_length=1)


class CancelOrderRequest(BaseModel):
    symbol: str = Field(min_length=1)
    quantity: str = Field(min_length=1)


def service(session):
    return KiwoomPendingOrderService(
        session, build_kiwoom_pending_order_client()
    )


@router.post("/by-uba/{user_broker_account_id}/sync")
async def sync_orders_by_uba(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
):
    try:
        return await service(session).synchronize(
            user_broker_account_id=user_broker_account_id,
        )
    except AccountIdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc


@router.get("/by-uba/{user_broker_account_id}")
def list_orders_by_uba(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
):
    rows = BrokerPendingOrderRepository(session).list_for_uba(
        "KIWOOM", user_broker_account_id
    )
    return [
        {
            "broker_pending_order_id": r.broker_pending_order_id,
            "user_broker_account_id": r.user_broker_account_id,
            "masked_account_ref": r.masked_account_ref,
            "broker_order_id": r.broker_order_id,
            "symbol": r.symbol,
            "side": r.side,
            "status_code": r.status_code,
            "order_quantity": str(r.order_quantity),
            "filled_quantity": str(r.filled_quantity),
            "remaining_quantity": str(r.remaining_quantity),
        }
        for r in rows
    ]


@router.post("/{account_number}/sync")
async def sync_orders_legacy(account_number: str):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "LEGACY_ACCOUNT_NUMBER_ONLY",
            "message": "Use /by-uba/{user_broker_account_id}/sync",
        },
    )


@router.get("/{account_number}")
def list_orders_legacy(account_number: str):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "LEGACY_ACCOUNT_NUMBER_ONLY",
            "message": "Use /by-uba/{user_broker_account_id}",
        },
    )


@router.post("/{order_id}/modify")
async def modify(
    order_id: str,
    request: ModifyOrderRequest,
    session: Session = Depends(get_db_session),
):
    return await service(session).modify(
        original_order_id=order_id,
        symbol=request.symbol,
        quantity=request.quantity,
        price=request.price,
        trade_type=request.trade_type,
    )


@router.post("/{order_id}/cancel")
async def cancel(
    order_id: str,
    request: CancelOrderRequest,
    session: Session = Depends(get_db_session),
):
    return await service(session).cancel(
        original_order_id=order_id,
        symbol=request.symbol,
        quantity=request.quantity,
    )
