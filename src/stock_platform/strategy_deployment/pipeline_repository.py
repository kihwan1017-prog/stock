from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.pipeline_entities import (
    StrategyDeploymentPipelineEntity,
)


class StrategyDeploymentPipelineRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start(
        self,
        *,
        selection_run_id: int,
        market_code: str,
        symbol: str | None,
        requested_by: str,
    ) -> StrategyDeploymentPipelineEntity:
        entity = StrategyDeploymentPipelineEntity(
            strategy_selection_run_id=selection_run_id,
            market_code=market_code.upper(),
            symbol=symbol.upper() if symbol else None,
            status_code="RUNNING",
            requested_by=requested_by,
            message="Strategy deployment pipeline started",
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def finish(
        self,
        *,
        entity: StrategyDeploymentPipelineEntity,
        status_code: str,
        message: str,
        detail_payload: dict,
        approval_run_id: int | None = None,
        deployment_id: int | None = None,
        runtime_switch_id: int | None = None,
        strategy_code: str | None = None,
    ) -> StrategyDeploymentPipelineEntity:
        entity.status_code = status_code
        entity.message = message
        entity.detail_payload = detail_payload
        entity.strategy_approval_run_id = approval_run_id
        entity.strategy_deployment_id = deployment_id
        entity.strategy_runtime_switch_id = runtime_switch_id
        entity.strategy_code = strategy_code
        entity.completed_at = datetime.now(timezone.utc)

        self._session.commit()
        self._session.refresh(entity)
        return entity

    def history(
        self,
        *,
        limit: int = 100,
    ) -> list[StrategyDeploymentPipelineEntity]:
        return list(
            self._session.scalars(
                select(StrategyDeploymentPipelineEntity)
                .order_by(
                    StrategyDeploymentPipelineEntity
                    .strategy_deployment_pipeline_id
                    .desc()
                )
                .limit(limit)
            )
        )
