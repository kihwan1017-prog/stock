from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from stock_platform.performance.leaderboard_repository import (
    StrategyLeaderboardRepository,
)
from stock_platform.performance.ranking_service import (
    StrategyPerformanceRankingService,
)


class StrategyLeaderboardService:
    def __init__(self, session: Session) -> None:
        self._ranking = StrategyPerformanceRankingService(
            session
        )
        self._repository = StrategyLeaderboardRepository(
            session
        )

    def generate_snapshot(
        self,
        *,
        snapshot_date: date,
        run_type: str | None,
        market_code: str | None,
        symbol: str | None,
        minimum_trade_count: int,
        limit: int,
    ):
        ranking = self._ranking.rank(
            run_type=run_type,
            market_code=market_code,
            symbol=symbol,
            minimum_trade_count=minimum_trade_count,
            limit=limit,
        )

        return self._repository.create_snapshot(
            snapshot_date=snapshot_date,
            run_type=(
                run_type.upper()
                if run_type
                else None
            ),
            market_code=(
                market_code.upper()
                if market_code
                else None
            ),
            symbol=(
                symbol.upper()
                if symbol
                else None
            ),
            minimum_trade_count=minimum_trade_count,
            ranking=ranking,
        )
