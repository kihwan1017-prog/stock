from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.job_models import JobRunHistory


class JobRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        job_name: str,
        job_group: str,
        trigger_type: str,
        request_payload: dict,
    ) -> JobRunHistory:
        entity = JobRunHistory(
            job_name=job_name,
            job_group=job_group,
            trigger_type=trigger_type,
            status_code="RUNNING",
            request_payload=request_payload,
            result_payload={},
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def complete(
        self,
        *,
        entity: JobRunHistory,
        status_code: str,
        finished_at: datetime,
        duration_ms: int,
        result_payload: dict,
        error_message: str | None,
    ) -> JobRunHistory:
        entity.status_code = status_code
        entity.finished_at = finished_at
        entity.duration_ms = duration_ms
        entity.result_payload = result_payload
        entity.error_message = error_message

        self._session.commit()
        self._session.refresh(entity)
        return entity

    def get(self, job_run_id: int) -> JobRunHistory | None:
        return self._session.get(JobRunHistory, job_run_id)

    def list_recent(
        self,
        *,
        job_name: str | None = None,
        status_code: str | None = None,
        limit: int = 100,
    ) -> list[JobRunHistory]:
        stmt = select(JobRunHistory)

        if job_name:
            stmt = stmt.where(
                JobRunHistory.job_name == job_name
            )

        if status_code:
            stmt = stmt.where(
                JobRunHistory.status_code
                == status_code.upper()
            )

        stmt = stmt.order_by(
            JobRunHistory.started_at.desc(),
            JobRunHistory.job_run_id.desc(),
        ).limit(limit)

        return list(self._session.scalars(stmt))
