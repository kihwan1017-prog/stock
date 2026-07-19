from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from stock_platform.common.settings import Settings, get_settings
from stock_platform.database.session import (
    get_db_session,
)
from stock_platform.risk_engine.dashboard_service import (
    RiskDashboardService,
)


router = APIRouter(
    prefix="/api/v1/dashboard/risk",
    tags=["Risk Dashboard"],
)


@router.get("")
def get_risk_dashboard(
    account_number: str | None = Query(
        default=None,
        min_length=1,
        description="계좌번호. 생략 시 KIWOOM_ACCOUNT_NUMBER 사용",
    ),
    recent_limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    # FE 모니터링은 account_number 없이 호출하므로 env 기본값으로 보강
    resolved = (account_number or settings.kiwoom_account_number or "").strip()
    if not resolved:
        resolved = "N/A"
    try:
        return RiskDashboardService(
            session
        ).build(
            account_number=resolved,
            recent_limit=recent_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
