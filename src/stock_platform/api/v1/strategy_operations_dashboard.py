from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from stock_platform.database.session import (
    get_db_session,
)
from stock_platform.strategy_deployment.dashboard_service import (
    StrategyOperationsDashboardService,
)


router = APIRouter(
    prefix="/api/v1/dashboard/strategy-operations",
    tags=["Strategy Operations Dashboard"],
)


@router.get("")
def get_strategy_operations_dashboard(
    market_code: str = Query(
        default="KRX",
        min_length=1,
    ),
    symbol: str | None = Query(default=None),
    limit: int = Query(
        default=20,
        ge=1,
        le=200,
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return StrategyOperationsDashboardService(
            session
        ).build(
            market_code=market_code,
            symbol=symbol,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
