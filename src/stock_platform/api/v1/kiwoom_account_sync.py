from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
    BrokerSnapshotBindingError,
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
    user_broker_account_id: int = Query(
        ..., gt=0, description="바인딩할 UBA ID (필수)"
    ),
    _: None = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    """UBA에 바인딩된 Kiwoom Snapshot 동기화 — 관리자 전용."""

    try:
        result = await KiwoomAccountSyncService(
            session=session,
            account_client=build_kiwoom_account_client(),
            user_broker_account_id=user_broker_account_id,
        ).synchronize(user_broker_account_id=user_broker_account_id)
        if isinstance(result, dict):
            for key in list(result.keys()):
                lowered = str(key).lower()
                if any(
                    frag in lowered
                    for frag in (
                        "secret",
                        "app_key",
                        "access_key",
                        "credential",
                        "token",
                    )
                ):
                    result.pop(key, None)
        return result
    except (ValueError, RuntimeError, BrokerSnapshotBindingError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/by-uba/{uba_id}")
def get_kiwoom_account_snapshot_by_uba(
    uba_id: int,
    _: None = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    from stock_platform.trading.account_masking import mask_account_number

    account, positions = BrokerAccountSnapshotRepository(
        session
    ).get_active_by_uba(int(uba_id))
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kiwoom account snapshot not found for UBA",
        )
    account_payload = {
        column.name: getattr(account, column.name)
        for column in account.__table__.columns
    }
    if "account_number" in account_payload:
        account_payload["account_number"] = mask_account_number(
            str(account_payload["account_number"] or "")
        )
        account_payload["masked_account_number"] = account_payload[
            "account_number"
        ]
    position_payloads = []
    for position in positions:
        row = {
            column.name: getattr(position, column.name)
            for column in position.__table__.columns
        }
        if "account_number" in row:
            row["account_number"] = mask_account_number(
                str(row["account_number"] or "")
            )
        position_payloads.append(row)
    return {"account": account_payload, "positions": position_payloads}


@router.get("/{account_number}")
def get_kiwoom_account_snapshot(
    account_number: str,
    _: None = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "LEGACY_ACCOUNT_NUMBER_ONLY",
            "message": "Use UBA-bound snapshot endpoints",
        },
    )
