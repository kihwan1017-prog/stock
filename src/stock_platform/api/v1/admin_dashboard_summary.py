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
    session: Session = Depends(get_db_session),
):
    """Admin 운영 Dashboard Summary — KPI·상태·최근 이벤트 통합."""

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
