from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.switch_entities import (
    StrategyRuntimeSwitchEntity,
)


class StrategyRuntimeSwitchRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        previous_deployment_id: int | None,
        target_deployment_id: int,
        requested_by: str,
        status_code: str,
        dry_run_payload: dict,
        previous_state_payload: dict,
    ) -> StrategyRuntimeSwitchEntity:
        entity = StrategyRuntimeSwitchEntity(
            previous_deployment_id=previous_deployment_id,
            target_deployment_id=target_deployment_id,
            requested_by=requested_by,
            status_code=status_code,
            dry_run_payload=dry_run_payload,
            previous_state_payload=previous_state_payload,
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def complete(
        self,
        *,
        entity: StrategyRuntimeSwitchEntity,
        status_code: str,
        target_state_payload: dict,
        completed_at,
        error_message: str | None = None,
    ) -> None:
        entity.status_code = status_code
        entity.target_state_payload = target_state_payload
        entity.completed_at = completed_at
        entity.error_message = error_message
        self._session.commit()
