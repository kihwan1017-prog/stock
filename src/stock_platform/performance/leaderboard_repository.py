from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.performance.leaderboard_entities import (
    StrategyLeaderboardEntryEntity,
    StrategyLeaderboardSnapshotEntity,
)
from stock_platform.performance.ranking_models import (
    StrategyRankingItem,
)


class StrategyLeaderboardRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_snapshot(
        self,
        *,
        snapshot_date: date,
        run_type: str | None,
        market_code: str | None,
        symbol: str | None,
        minimum_trade_count: int,
        ranking: list[StrategyRankingItem],
    ) -> StrategyLeaderboardSnapshotEntity:
        existing = self._session.scalar(
            select(StrategyLeaderboardSnapshotEntity).where(
                StrategyLeaderboardSnapshotEntity.snapshot_date
                == snapshot_date,
                StrategyLeaderboardSnapshotEntity.run_type
                == run_type,
                StrategyLeaderboardSnapshotEntity.market_code
                == market_code,
                StrategyLeaderboardSnapshotEntity.symbol
                == symbol,
                StrategyLeaderboardSnapshotEntity.minimum_trade_count
                == minimum_trade_count,
            )
        )

        if existing is not None:
            raise ValueError(
                "Leaderboard snapshot already exists for this scope and date"
            )

        snapshot = StrategyLeaderboardSnapshotEntity(
            snapshot_date=snapshot_date,
            run_type=run_type,
            market_code=market_code,
            symbol=symbol,
            minimum_trade_count=minimum_trade_count,
            strategy_count=len(ranking),
            ranking_payload=[
                {
                    "rank": item.rank,
                    "strategy_code": item.strategy_code,
                    "market_code": item.market_code,
                    "symbol": item.symbol,
                    "run_type": item.run_type,
                    "score": str(item.score),
                    "total_return_rate": str(
                        item.total_return_rate
                    ),
                    "maximum_drawdown_rate": str(
                        item.maximum_drawdown_rate
                    ),
                    "sharpe_ratio": (
                        str(item.sharpe_ratio)
                        if item.sharpe_ratio is not None
                        else None
                    ),
                    "sortino_ratio": (
                        str(item.sortino_ratio)
                        if item.sortino_ratio is not None
                        else None
                    ),
                    "win_rate": str(item.win_rate),
                    "profit_factor": (
                        str(item.profit_factor)
                        if item.profit_factor is not None
                        else None
                    ),
                    "total_trade_count": item.total_trade_count,
                    "strategy_performance_run_id": (
                        item.strategy_performance_run_id
                    ),
                }
                for item in ranking
            ],
        )
        self._session.add(snapshot)
        self._session.flush()

        for item in ranking:
            self._session.add(
                StrategyLeaderboardEntryEntity(
                    strategy_leaderboard_snapshot_id=(
                        snapshot
                        .strategy_leaderboard_snapshot_id
                    ),
                    rank_no=item.rank,
                    strategy_performance_run_id=(
                        item.strategy_performance_run_id
                    ),
                    strategy_code=item.strategy_code,
                    market_code=item.market_code,
                    symbol=item.symbol,
                    run_type=item.run_type,
                    score=item.score,
                    total_return_rate=(
                        item.total_return_rate
                    ),
                    maximum_drawdown_rate=(
                        item.maximum_drawdown_rate
                    ),
                    sharpe_ratio=item.sharpe_ratio,
                    sortino_ratio=item.sortino_ratio,
                    win_rate=item.win_rate,
                    profit_factor=item.profit_factor,
                    total_trade_count=(
                        item.total_trade_count
                    ),
                )
            )

        self._session.commit()
        self._session.refresh(snapshot)
        return snapshot

    def get_snapshot(
        self,
        *,
        snapshot_id: int,
    ):
        snapshot = self._session.get(
            StrategyLeaderboardSnapshotEntity,
            snapshot_id,
        )
        entries = list(
            self._session.scalars(
                select(StrategyLeaderboardEntryEntity)
                .where(
                    StrategyLeaderboardEntryEntity
                    .strategy_leaderboard_snapshot_id
                    == snapshot_id
                )
                .order_by(
                    StrategyLeaderboardEntryEntity.rank_no
                )
            )
        )
        return snapshot, entries

    def list_history(
        self,
        *,
        run_type: str | None = None,
        market_code: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ):
        statement = select(
            StrategyLeaderboardSnapshotEntity
        )

        if run_type:
            statement = statement.where(
                StrategyLeaderboardSnapshotEntity.run_type
                == run_type.upper()
            )

        if market_code:
            statement = statement.where(
                StrategyLeaderboardSnapshotEntity.market_code
                == market_code.upper()
            )

        if symbol:
            statement = statement.where(
                StrategyLeaderboardSnapshotEntity.symbol
                == symbol.upper()
            )

        return list(
            self._session.scalars(
                statement.order_by(
                    StrategyLeaderboardSnapshotEntity
                    .snapshot_date.desc(),
                    StrategyLeaderboardSnapshotEntity
                    .strategy_leaderboard_snapshot_id.desc(),
                ).limit(limit)
            )
        )
