from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from stock_platform.database.session import get_db_session
from stock_platform.performance.dashboard_service import StrategyPerformanceDashboardService

router = APIRouter(
    prefix="/api/v1/dashboard/strategy-performance",
    tags=["Strategy Performance Dashboard"],
)

@router.get("")
def get_strategy_performance_dashboard(
    run_type: str | None = Query(default=None),
    market_code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    minimum_trade_count: int = Query(default=1, ge=0),
    ranking_limit: int = Query(default=20, ge=1, le=100),
    history_limit: int = Query(default=20, ge=1, le=100),
    recent_run_limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),
):
    return StrategyPerformanceDashboardService(session).build(
        run_type=run_type, market_code=market_code, symbol=symbol,
        minimum_trade_count=minimum_trade_count,
        ranking_limit=ranking_limit, history_limit=history_limit,
        recent_run_limit=recent_run_limit,
    )
