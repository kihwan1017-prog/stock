from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.job_repository import (
    JobRunRepository,
)
from stock_platform.operation.job_service import (
    JobExecutionService,
)
from stock_platform.scheduler.factory import (
    build_job_registry,
)


class SchedulerService:
    """등록 작업 조회 및 수동 실행 진입점."""

    def __init__(self, session: Session) -> None:
        self._registry = build_job_registry(session)
        self._execution = JobExecutionService(
            JobRunRepository(session)
        )

    def list_jobs(self):
        return self._registry.list_jobs()

    async def execute(
        self,
        *,
        job_name: str,
        payload: dict[str, Any],
        trigger_type: str = "MANUAL",
    ):
        from stock_platform.trading.account_identity import (
            AccountIdentityError,
            validate_scheduler_account_payload,
        )

        job = self._registry.get(job_name)
        safe_payload = dict(payload or {})
        # job_type 미지정 시 job_name 으로 검증
        if "job_type" not in safe_payload:
            safe_payload["job_type"] = job.name
        try:
            validate_scheduler_account_payload(
                safe_payload,
                job_type=str(safe_payload.get("job_type") or job.name),
            )
        except AccountIdentityError as exc:
            raise ValueError(f"{exc.code.value}: {exc}") from exc

        history, result = await self._execution.execute(
            job_name=job.name,
            job_group=job.group,
            trigger_type=trigger_type.upper(),
            request_payload=payload,
            handler=lambda: job.handler(payload),
        )

        return history, result
