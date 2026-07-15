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
from stock_platform.strategy_deployment.performance_monitor_repository import (
    DeploymentPerformanceRepository,
)
from stock_platform.strategy_deployment.performance_monitor_runtime import (
    deployment_performance_monitor_manager,
)


router = APIRouter(
    prefix="/api/v1/strategy-deployment-performance",
    tags=["Strategy Deployment Performance"],
)


@router.post("/check-active")
def check_active_deployment_performance(
    market_code: str = Query(default="KRX"),
    symbol: str | None = Query(default=None),
):
    try:
        return (
            deployment_performance_monitor_manager
            .check_active(
                market_code=market_code,
                symbol=symbol,
            )
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/status")
def get_deployment_performance_monitor_status():
    return (
        deployment_performance_monitor_manager
        .status()
    )


@router.get("/history")
def get_deployment_performance_history(
    deployment_id: int | None = Query(
        default=None
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    session: Session = Depends(get_db_session),
):
    return DeploymentPerformanceRepository(
        session
    ).recent(
        deployment_id=deployment_id,
        limit=limit,
    )
