from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
)
from stock_platform.broker.kiwoom.account_factory import (
    build_kiwoom_account_client,
)
from stock_platform.broker.kiwoom.account_sync_service import (
    KiwoomAccountSyncService,
)
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/broker/kiwoom/account",
    tags=["Kiwoom Account"],
)


@router.post("/sync")
async def synchronize_kiwoom_account(
    session: Session = Depends(get_db_session),
):
    try:
        return await KiwoomAccountSyncService(
            session=session,
            account_client=build_kiwoom_account_client(),
        ).synchronize()
    except (ValueError, RuntimeError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/{account_number}")
def get_kiwoom_account_snapshot(
    account_number: str,
    session: Session = Depends(get_db_session),
):
    account, positions = (
        BrokerAccountSnapshotRepository(session)
        .get_latest(
            broker_code="KIWOOM",
            account_number=account_number,
        )
    )

    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kiwoom account snapshot not found",
        )

    return {
        "account": account,
        "positions": positions,
    }
