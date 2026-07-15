from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from sqlalchemy.orm import Session

from stock_platform.database.session import (
    get_db_session,
)
from stock_platform.performance.ranking_service import (
    StrategyPerformanceRankingService,
)
from stock_platform.performance.summary_service import (
    StrategyPerformanceSummaryService,
)


router = APIRouter(
    prefix="/api/v1/strategy-ranking",
    tags=["Strategy Ranking"],
)


@router.get("")
def get_strategy_ranking(
    run_type: str | None = Query(default=None),
    market_code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    minimum_trade_count: int = Query(
        default=1,
        ge=0,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
    ),
    session: Session = Depends(get_db_session),
):
    return StrategyPerformanceRankingService(
        session
    ).rank(
        run_type=run_type,
        market_code=market_code,
        symbol=symbol,
        minimum_trade_count=minimum_trade_count,
        limit=limit,
    )


@router.get("/summary")
def get_strategy_performance_summary(
    strategy_code: str | None = Query(
        default=None
    ),
    run_type: str | None = Query(default=None),
    market_code: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
):
    return StrategyPerformanceSummaryService(
        session
    ).summarize(
        strategy_code=strategy_code,
        run_type=run_type,
        market_code=market_code,
    )
