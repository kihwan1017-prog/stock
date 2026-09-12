from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.broker.credential_adapter_factory import (
    build_kiwoom_account_client_for_uba,
    build_kiwoom_pending_order_client_for_uba,
)
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
)
from stock_platform.broker.kiwoom.account_sync_service import (
    KiwoomAccountSyncService,
)
from stock_platform.broker.kiwoom.account_state_sync_service import (
    KiwoomAccountStateSyncService,
)
from stock_platform.broker.kiwoom.client import KiwoomRestError
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
    user_broker_account_id: int = Query(..., ge=1),
    _: None = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    """예수금·보유·평가손익·미체결을 일괄 동기화한다 (UBA 필수)."""
    try:
        account_client, _account_number = build_kiwoom_account_client_for_uba(
            session, user_broker_account_id
        )
        result = await KiwoomAccountStateSyncService(
            session=session,
            account_sync_service=KiwoomAccountSyncService(
                session=session,
                account_client=account_client,
                user_broker_account_id=user_broker_account_id,
            ),
            pending_order_service=KiwoomPendingOrderService(
                session,
                build_kiwoom_pending_order_client_for_uba(
                    session, user_broker_account_id
                ),
            ),
        ).synchronize(user_broker_account_id=user_broker_account_id)
    except BrokerCredentialVaultError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except (ValueError, RuntimeError, KiwoomRestError) as exc:
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
