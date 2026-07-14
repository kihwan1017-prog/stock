from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.pipeline_models import (
    PipelineRun,
    PipelineStepRun,
)


class PipelineRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_pipeline(
        self,
        *,
        pipeline_name: str,
        trigger_type: str,
        request_payload: dict,
    ) -> PipelineRun:
        entity = PipelineRun(
            pipeline_name=pipeline_name,
            trigger_type=trigger_type,
            status_code="RUNNING",
            request_payload=request_payload,
            result_payload={},
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def create_step(
        self,
        *,
        pipeline_run_id: int,
        step_order: int,
        step_name: str,
        job_name: str,
    ) -> PipelineStepRun:
        entity = PipelineStepRun(
            pipeline_run_id=pipeline_run_id,
            step_order=step_order,
            step_name=step_name,
            job_name=job_name,
            status_code="PENDING",
            attempt_count=0,
            result_payload={},
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def update_step(
        self,
        *,
        entity: PipelineStepRun,
        status_code: str,
        attempt_count: int,
        started_at: datetime | None,
        finished_at: datetime | None,
        result_payload: dict,
        error_message: str | None,
    ) -> PipelineStepRun:
        entity.status_code = status_code
        entity.attempt_count = attempt_count
        entity.started_at = started_at
        entity.finished_at = finished_at
        entity.result_payload = result_payload
        entity.error_message = error_message
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def complete_pipeline(
        self,
        *,
        entity: PipelineRun,
        status_code: str,
        finished_at: datetime,
        result_payload: dict,
        error_message: str | None,
    ) -> PipelineRun:
        entity.status_code = status_code
        entity.finished_at = finished_at
        entity.result_payload = result_payload
        entity.error_message = error_message
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def get_latest(
        self,
        *,
        pipeline_name: str | None = None,
    ) -> PipelineRun | None:
        stmt = select(PipelineRun)

        if pipeline_name:
            stmt = stmt.where(
                PipelineRun.pipeline_name == pipeline_name
            )

        stmt = stmt.order_by(
            PipelineRun.started_at.desc(),
            PipelineRun.pipeline_run_id.desc(),
        ).limit(1)

        return self._session.scalar(stmt)

    def list_steps(
        self,
        pipeline_run_id: int,
    ) -> list[PipelineStepRun]:
        stmt = (
            select(PipelineStepRun)
            .where(
                PipelineStepRun.pipeline_run_id
                == pipeline_run_id
            )
            .order_by(
                PipelineStepRun.step_order.asc()
            )
        )
        return list(self._session.scalars(stmt))
