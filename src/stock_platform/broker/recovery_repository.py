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
from stock_platform.common.json_safe import to_jsonable


class BrokerRecoveryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start_run(
        self,
        *,
        trigger_type: str | None = None,
        broker_code: str | None = None,
        user_id: int | None = None,
        paper_account_id: int | None = None,
        user_broker_account_id: int | None = None,
        requested_by: str | None = None,
    ) -> BrokerRecoveryRunEntity:
        entity = BrokerRecoveryRunEntity(
            status_code="RUNNING",
            trigger_type=trigger_type,
            broker_code=broker_code,
            user_id=user_id,
            paper_account_id=paper_account_id,
            user_broker_account_id=user_broker_account_id,
            requested_by=requested_by,
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
        entity.result_payload = to_jsonable(
            {
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
        )

        for item in result.steps:
            self._session.add(
                BrokerRecoveryStepEntity(
                    broker_recovery_run_id=(
                        entity.broker_recovery_run_id
                    ),
                    component_code=item.component.value,
                    status_code=item.status.value,
                    message=item.message,
                    detail_payload=to_jsonable(item.detail),
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

    def list_runs(
        self,
        *,
        broker_code: str | None = None,
        status_code: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BrokerRecoveryRunEntity]:
        stmt = select(BrokerRecoveryRunEntity)
        if broker_code:
            stmt = stmt.where(
                BrokerRecoveryRunEntity.broker_code
                == broker_code.upper()
            )
        if status_code:
            stmt = stmt.where(
                BrokerRecoveryRunEntity.status_code
                == status_code.upper()
            )
        return list(
            self._session.scalars(
                stmt.order_by(
                    BrokerRecoveryRunEntity.started_at.desc()
                )
                .offset(offset)
                .limit(limit)
            )
        )

    def get_run(self, run_id: int) -> BrokerRecoveryRunEntity | None:
        return self._session.get(BrokerRecoveryRunEntity, run_id)
