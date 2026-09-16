from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.risk_engine.dashboard_service import (
    RiskDashboardService,
)


router = APIRouter(
    prefix="/api/v1/dashboard/risk",
    tags=["Risk Dashboard"],
    dependencies=[Depends(require_admin)],
)


@router.get("")
def get_risk_dashboard(
    user_broker_account_id: int | None = Query(
        default=None,
        ge=1,
        description="LIVE UBA ID (optional — omit for global status)",
    ),
    recent_limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
):
    try:
        return RiskDashboardService(session).build(
            user_broker_account_id=user_broker_account_id,
            recent_limit=recent_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
