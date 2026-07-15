from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.recovery_entities import (
    BrokerRecoveryRunEntity,
    BrokerRecoveryStepEntity,
)
from stock_platform.broker.recovery_models import (
    RecoveryRunResult,
)


class BrokerRecoveryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start_run(self) -> BrokerRecoveryRunEntity:
        entity = BrokerRecoveryRunEntity(
            status_code="RUNNING",
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def finish_run(
        self,
        *,
        entity: BrokerRecoveryRunEntity,
        result: RecoveryRunResult,
    ) -> BrokerRecoveryRunEntity:
        entity.status_code = (
            "SUCCESS" if result.success else "FAILED"
        )
        entity.finished_at = result.finished_at
        entity.result_payload = {
            "success": result.success,
            "steps": [
                {
                    "component": item.component.value,
                    "status": item.status.value,
                    "message": item.message,
                    "detail": item.detail,
                    "started_at": item.started_at.isoformat(),
                    "finished_at": item.finished_at.isoformat(),
                }
                for item in result.steps
            ],
        }

        for item in result.steps:
            self._session.add(
                BrokerRecoveryStepEntity(
                    broker_recovery_run_id=(
                        entity.broker_recovery_run_id
                    ),
                    component_code=item.component.value,
                    status_code=item.status.value,
                    message=item.message,
                    detail_payload=item.detail,
                    started_at=item.started_at,
                    finished_at=item.finished_at,
                )
            )

        self._session.commit()
        self._session.refresh(entity)
        return entity

    def fail_run(
        self,
        *,
        entity: BrokerRecoveryRunEntity,
        error_message: str,
    ) -> None:
        entity.status_code = "FAILED"
        entity.finished_at = datetime.now().astimezone()
        entity.error_message = error_message
        self._session.commit()

    def latest(self):
        return self._session.scalar(
            select(BrokerRecoveryRunEntity)
            .order_by(
                BrokerRecoveryRunEntity.started_at.desc(),
                BrokerRecoveryRunEntity
                .broker_recovery_run_id.desc(),
            )
            .limit(1)
        )
