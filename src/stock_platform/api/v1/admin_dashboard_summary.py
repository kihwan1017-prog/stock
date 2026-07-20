from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.auth.account_ownership import (
    assert_trading_account_access,
)
from stock_platform.auth.deps import AuthenticatedUser, get_current_user
from stock_platform.operation.admin_dashboard_summary_service import (
    AdminDashboardSummaryService,
)


router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["Dashboard"],
)


@router.get("/admin-summary")
async def get_admin_dashboard_summary(
    account_id: int = Query(default=1, gt=0),
    market_code: str = Query(default="KRX"),
    mode_code: str = Query(default="PAPER"),
    recent_limit: int = Query(default=10, ge=1, le=100),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    """Dashboard Summary — Admin 전체 / 일반 유저는 본인 계좌만."""

    assert_trading_account_access(user, account_id, session)

    try:
        return await AdminDashboardSummaryService(
            session
        ).build(
            account_id=account_id,
            market_code=market_code,
            mode_code=mode_code,
            recent_limit=recent_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
