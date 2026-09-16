"""회원 포트폴리오 이력·요약 API — STEP66."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.account_ownership import (
    assert_paper_account_access,
)
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.trading.portfolio_snapshot_service import (
    PortfolioSnapshotService,
)


router = APIRouter(
    prefix="/api/v1/user/portfolio",
    tags=["User Portfolio"],
)


class CreateSnapshotRequest(BaseModel):
    account_id: int = Field(gt=0)
    snapshot_date: date | None = None
    mode_code: str = Field(default="PAPER", max_length=20)


def _service(session: Session) -> PortfolioSnapshotService:
    return PortfolioSnapshotService(session)


@router.get("/history")
def get_portfolio_history(
    account_id: int = Query(..., gt=0),
    period: str | None = Query(
        "30d",
        description="7d | 30d | 90d | 1y | all",
    ),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """본인 계좌 일별 자산 이력."""

    assert_paper_account_access(user, account_id, session)
    return _service(session).history(
        user_id=user.user_id,
        account_id=account_id,
        period=period,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/summary")
def get_portfolio_summary(
    account_id: int = Query(..., gt=0),
    period: str | None = Query("30d"),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """현재 자산 + MDD + 기간 수익률."""

    assert_paper_account_access(user, account_id, session)
    return _service(session).summary(
        user_id=user.user_id,
        account_id=account_id,
        period=period,
        date_from=date_from,
        date_to=date_to,
    )


@router.post("/snapshot")
def create_portfolio_snapshot(
    request: CreateSnapshotRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    """사용자 요청 스냅샷 (당일 account+date upsert)."""

    assert_paper_account_access(
        user, request.account_id, session
    )
    try:
        row = _service(session).capture_account(
            account_id=request.account_id,
            snapshot_date=request.snapshot_date,
            mode_code=request.mode_code,
            force_user_id=user.user_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return PortfolioSnapshotService._row_dict(row)
