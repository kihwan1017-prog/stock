from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.performance.walk_forward_entities import (
    WalkForwardWindowMetricEntity,
)


class WalkForwardWindowMetricRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_many(
        self,
        *,
        strategy_performance_run_id: int,
        rows: list[WalkForwardWindowMetricEntity],
    ) -> int:
        for row in rows:
            row.strategy_performance_run_id = (
                strategy_performance_run_id
            )
            self._session.add(row)

        self._session.commit()
        return len(rows)

    def list_by_run(
        self,
        *,
        strategy_performance_run_id: int,
    ) -> list[WalkForwardWindowMetricEntity]:
        return list(
            self._session.scalars(
                select(WalkForwardWindowMetricEntity)
                .where(
                    WalkForwardWindowMetricEntity
                    .strategy_performance_run_id
                    == strategy_performance_run_id
                )
                .order_by(
                    WalkForwardWindowMetricEntity.window_no
                )
            )
        )
