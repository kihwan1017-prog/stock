from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.broker.kiwoom.pending_factory import build_kiwoom_pending_order_client
from stock_platform.broker.kiwoom.pending_service import KiwoomPendingOrderService
from stock_platform.broker.pending_repository import BrokerPendingOrderRepository

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
    return KiwoomPendingOrderService(session, build_kiwoom_pending_order_client())

@router.post("/{account_number}/sync")
async def sync_orders(account_number: str, session: Session = Depends(get_db_session)):
    return await service(session).synchronize(account_number)

@router.get("/{account_number}")
def list_orders(account_number: str, session: Session = Depends(get_db_session)):
    return BrokerPendingOrderRepository(session).list_for_account("KIWOOM", account_number)

@router.post("/{order_id}/modify")
async def modify(order_id: str, request: ModifyOrderRequest,
                 session: Session = Depends(get_db_session)):
    return await service(session).modify(
        original_order_id=order_id, symbol=request.symbol,
        quantity=request.quantity, price=request.price,
        trade_type=request.trade_type,
    )

@router.post("/{order_id}/cancel")
async def cancel(order_id: str, request: CancelOrderRequest,
                 session: Session = Depends(get_db_session)):
    return await service(session).cancel(
        original_order_id=order_id, symbol=request.symbol,
        quantity=request.quantity,
    )
