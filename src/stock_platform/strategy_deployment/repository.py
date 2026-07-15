from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.entities import (
    StrategyDeploymentEntity,
    StrategyDeploymentHistoryEntity,
)


class StrategyDeploymentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active(
        self,
        *,
        market_code: str,
        symbol: str | None,
        mode_code: str,
    ) -> StrategyDeploymentEntity | None:
        statement = select(
            StrategyDeploymentEntity
        ).where(
            StrategyDeploymentEntity.market_code
            == market_code.upper(),
            StrategyDeploymentEntity.mode_code
            == mode_code.upper(),
            StrategyDeploymentEntity.status_code
            == "ACTIVE",
        )

        if symbol is None:
            statement = statement.where(
                StrategyDeploymentEntity.symbol.is_(None)
            )
        else:
            statement = statement.where(
                StrategyDeploymentEntity.symbol
                == symbol.upper()
            )

        return self._session.scalar(
            statement.order_by(
                StrategyDeploymentEntity
                .strategy_deployment_id.desc()
            ).limit(1)
        )

    def create(
        self,
        *,
        strategy_code: str,
        strategy_performance_run_id: int,
        market_code: str,
        symbol: str | None,
        mode_code: str,
        parameter_payload: dict,
        requested_by: str,
    ) -> StrategyDeploymentEntity:
        entity = StrategyDeploymentEntity(
            strategy_code=strategy_code,
            strategy_performance_run_id=(
                strategy_performance_run_id
            ),
            market_code=market_code.upper(),
            symbol=symbol.upper() if symbol else None,
            mode_code=mode_code.upper(),
            status_code="PENDING",
            parameter_payload=parameter_payload,
            requested_by=requested_by,
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def add_history(
        self,
        *,
        deployment_id: int,
        action_code: str,
        actor: str,
        message: str,
        detail_payload: dict | None = None,
    ) -> None:
        self._session.add(
            StrategyDeploymentHistoryEntity(
                strategy_deployment_id=deployment_id,
                action_code=action_code,
                actor=actor,
                message=message,
                detail_payload=detail_payload or {},
            )
        )
        self._session.commit()

    def get(
        self,
        deployment_id: int,
    ) -> StrategyDeploymentEntity | None:
        return self._session.get(
            StrategyDeploymentEntity,
            deployment_id,
        )
