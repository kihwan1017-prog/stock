from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.performance.leaderboard_entities import (
    StrategyLeaderboardEntryEntity,
    StrategyLeaderboardSnapshotEntity,
)


class StrategyLeaderboardTrendService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def strategy_history(
        self,
        *,
        strategy_code: str,
        limit: int = 100,
    ) -> list[dict]:
        rows = list(
            self._session.execute(
                select(
                    StrategyLeaderboardSnapshotEntity,
                    StrategyLeaderboardEntryEntity,
                )
                .join(
                    StrategyLeaderboardEntryEntity,
                    StrategyLeaderboardEntryEntity
                    .strategy_leaderboard_snapshot_id
                    == StrategyLeaderboardSnapshotEntity
                    .strategy_leaderboard_snapshot_id,
                )
                .where(
                    StrategyLeaderboardEntryEntity.strategy_code
                    == strategy_code
                )
                .order_by(
                    StrategyLeaderboardSnapshotEntity
                    .snapshot_date.desc()
                )
                .limit(limit)
            ).all()
        )

        result = []

        previous_rank: int | None = None

        for snapshot, entry in rows:
            rank_change = (
                None
                if previous_rank is None
                else previous_rank - entry.rank_no
            )
            result.append(
                {
                    "snapshot_id": (
                        snapshot
                        .strategy_leaderboard_snapshot_id
                    ),
                    "snapshot_date": snapshot.snapshot_date,
                    "rank": entry.rank_no,
                    "rank_change": rank_change,
                    "score": str(entry.score),
                    "market_code": entry.market_code,
                    "symbol": entry.symbol,
                    "run_type": entry.run_type,
                    "strategy_performance_run_id": (
                        entry.strategy_performance_run_id
                    ),
                }
            )
            previous_rank = entry.rank_no

        return result
