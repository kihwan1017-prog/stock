from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
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
    # None이면 REALTIME_PAPER_ACCOUNT_ID 설정값 사용 (하드코딩 1 제거)
    account_id: int | None = Query(default=None, gt=0),
    market_code: str = Query(default="KRX"),
    mode_code: str = Query(default="PAPER"),
    recent_limit: int = Query(default=10, ge=1, le=100),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    """Dashboard Summary — Admin 전체 / 일반 유저는 본인 계좌만."""

    resolved_account_id = (
        account_id
        if account_id is not None
        else get_settings().realtime_paper_account_id
    )
    assert_trading_account_access(user, resolved_account_id, session)

    try:
        return await AdminDashboardSummaryService(
            session
        ).build(
            account_id=resolved_account_id,
            market_code=market_code,
            mode_code=mode_code,
            recent_limit=recent_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
