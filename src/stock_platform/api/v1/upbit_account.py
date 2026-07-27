from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
    BrokerSnapshotBindingError,
)
from stock_platform.broker.upbit.account_factory import (
    build_upbit_private_client,
)
from stock_platform.broker.upbit.account_sync_service import (
    UpbitAccountSyncService,
)
from stock_platform.broker.upbit.exceptions import UpbitError
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/broker/upbit/account",
    tags=["Upbit Account"],
)


@router.get("/status")
def get_upbit_account_status(
    _: None = Depends(require_admin),
):
    client = build_upbit_private_client(require_credentials=False)
    return client.connection_status()


@router.post("/connection-test")
async def test_upbit_account_connection(
    _: None = Depends(require_admin),
):
    try:
        client = build_upbit_private_client()
        return await client.test_connection()
    except (ValueError, UpbitError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/sync")
async def synchronize_upbit_account(
    user_broker_account_id: int = Query(..., gt=0),
    _: None = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    try:
        result = await UpbitAccountSyncService(
            session=session,
            private_client=build_upbit_private_client(),
            user_broker_account_id=user_broker_account_id,
        ).synchronize(user_broker_account_id=user_broker_account_id)
        session.commit()
        if isinstance(result, dict):
            for key in list(result.keys()):
                lowered = str(key).lower()
                if any(
                    frag in lowered
                    for frag in (
                        "secret",
                        "access_key",
                        "credential",
                        "token",
                    )
                ):
                    result.pop(key, None)
        return result
    except (
        ValueError,
        UpbitError,
        RuntimeError,
        BrokerSnapshotBindingError,
    ) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/snapshot")
def get_upbit_account_snapshot(
    user_broker_account_id: int = Query(..., gt=0),
    _: None = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    account, positions = BrokerAccountSnapshotRepository(
        session
    ).get_active_by_uba(int(user_broker_account_id))
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upbit account snapshot not found for UBA",
        )
    account_payload = {
        column.name: getattr(account, column.name)
        for column in account.__table__.columns
    }
    account_payload.pop("account_number", None)
    position_payloads = [
        {
            column.name: getattr(position, column.name)
            for column in position.__table__.columns
            if column.name != "account_number"
        }
        for position in positions
    ]
    return {"account": account_payload, "positions": position_payloads}


@router.post("/reconcile-orders")
def reconcile_upbit_open_orders(
    _: None = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    from stock_platform.broker.upbit.order_reconcile_service import (
        UpbitOrderReconcileService,
    )

    try:
        result = UpbitOrderReconcileService(session).reconcile_open_orders()
        session.commit()
        return result
    except (ValueError, UpbitError, RuntimeError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
