from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.performance_monitor_entities import (
    StrategyDeploymentPerformanceEntity,
)
from stock_platform.strategy_deployment.performance_monitor_models import (
    DeploymentPerformanceSnapshot,
)


class DeploymentPerformanceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(
        self,
        snapshot: DeploymentPerformanceSnapshot,
    ) -> StrategyDeploymentPerformanceEntity:
        entity = StrategyDeploymentPerformanceEntity(
            strategy_deployment_id=snapshot.deployment_id,
            strategy_code=snapshot.strategy_code,
            status_code=snapshot.status.value,
            total_trade_count=snapshot.total_trade_count,
            total_return_rate=snapshot.total_return_rate,
            maximum_drawdown_rate=(
                snapshot.maximum_drawdown_rate
            ),
            win_rate=snapshot.win_rate,
            profit_factor=snapshot.profit_factor,
            consecutive_losses=snapshot.consecutive_losses,
            check_payload=snapshot.checks,
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def recent(
        self,
        *,
        deployment_id: int | None = None,
        limit: int = 100,
    ):
        statement = select(
            StrategyDeploymentPerformanceEntity
        )

        if deployment_id is not None:
            statement = statement.where(
                StrategyDeploymentPerformanceEntity
                .strategy_deployment_id
                == deployment_id
            )

        return list(
            self._session.scalars(
                statement.order_by(
                    StrategyDeploymentPerformanceEntity
                    .strategy_deployment_performance_id
                    .desc()
                )
                .limit(limit)
            )
        )
