from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.account_factory import (
    build_kiwoom_account_client,
)
from stock_platform.broker.kiwoom.account_state_sync_service import (
    KiwoomAccountStateSyncService,
)
from stock_platform.broker.kiwoom.account_sync_service import (
    KiwoomAccountSyncService,
)
from stock_platform.broker.kiwoom.pending_factory import (
    build_kiwoom_pending_order_client,
)
from stock_platform.broker.kiwoom.pending_service import (
    KiwoomPendingOrderService,
)
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/broker/kiwoom/account-state",
    tags=["Kiwoom Account State"],
)


@router.post("/sync")
async def synchronize_kiwoom_account_state(
    session: Session = Depends(get_db_session),
):
    """예수금·보유·평가손익·미체결을 일괄 동기화한다."""
    try:
        result = await KiwoomAccountStateSyncService(
            session=session,
            account_sync_service=KiwoomAccountSyncService(
                session=session,
                account_client=build_kiwoom_account_client(),
            ),
            pending_order_service=KiwoomPendingOrderService(
                session,
                build_kiwoom_pending_order_client(),
            ),
        ).synchronize()
    except (ValueError, RuntimeError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "account": result.account,
        "pending_orders": result.pending_orders,
        "fields": result.fields,
    }
