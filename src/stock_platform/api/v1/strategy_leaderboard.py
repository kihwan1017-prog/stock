from datetime import date

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import (
    get_db_session,
)
from stock_platform.performance.leaderboard_repository import (
    StrategyLeaderboardRepository,
)
from stock_platform.performance.leaderboard_service import (
    StrategyLeaderboardService,
)
from stock_platform.performance.leaderboard_trend_service import (
    StrategyLeaderboardTrendService,
)


router = APIRouter(
    prefix="/api/v1/strategy-leaderboard",
    tags=["Strategy Leaderboard"],
)


class LeaderboardSnapshotRequest(BaseModel):
    snapshot_date: date
    run_type: str | None = Field(
        default=None,
        max_length=30,
    )
    market_code: str | None = Field(
        default=None,
        max_length=30,
    )
    symbol: str | None = Field(
        default=None,
        max_length=30,
    )
    minimum_trade_count: int = Field(
        default=1,
        ge=0,
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=500,
    )


@router.post("/snapshots")
def create_leaderboard_snapshot(
    request: LeaderboardSnapshotRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return StrategyLeaderboardService(
            session
        ).generate_snapshot(
            snapshot_date=request.snapshot_date,
            run_type=request.run_type,
            market_code=request.market_code,
            symbol=request.symbol,
            minimum_trade_count=(
                request.minimum_trade_count
            ),
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/snapshots/{snapshot_id}")
def get_leaderboard_snapshot(
    snapshot_id: int,
    session: Session = Depends(get_db_session),
):
    snapshot, entries = StrategyLeaderboardRepository(
        session
    ).get_snapshot(snapshot_id=snapshot_id)

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leaderboard snapshot not found",
        )

    return {
        "snapshot": snapshot,
        "entries": entries,
    }


@router.get("/history")
def list_leaderboard_history(
    run_type: str | None = Query(default=None),
    market_code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
):
    return StrategyLeaderboardRepository(
        session
    ).list_history(
        run_type=run_type,
        market_code=market_code,
        symbol=symbol,
        limit=limit,
    )


@router.get("/strategies/{strategy_code}/history")
def get_strategy_rank_history(
    strategy_code: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
):
    return StrategyLeaderboardTrendService(
        session
    ).strategy_history(
        strategy_code=strategy_code,
        limit=limit,
    )
