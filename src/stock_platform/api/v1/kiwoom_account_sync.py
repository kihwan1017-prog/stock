from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
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
    _: None = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    """
    서버 공용 Kiwoom credential 로 스냅샷 동기화 (관리자 전용).
    회원별 연결은 POST /api/v1/user/accounts 를 사용한다.
    """

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
    _: None = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    """관리자 전용 — 응답에 전체 계좌번호를 최소화한다."""

    from stock_platform.trading.account_masking import mask_account_number

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

    # ORM 객체를 dict로 변환하며 계좌번호 마스킹
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

    return {
        "account": account_payload,
        "positions": position_payloads,
    }
