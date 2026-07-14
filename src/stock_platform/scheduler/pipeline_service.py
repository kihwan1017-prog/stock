from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.pipeline_repository import (
    PipelineRepository,
)
from stock_platform.scheduler.service import SchedulerService


@dataclass(frozen=True, slots=True)
class PipelineStepDefinition:
    step_order: int
    step_name: str
    job_name: str
    payload: dict[str, Any]
    max_attempts: int = 3
    retry_delay_seconds: float = 5.0


class DailyPipelineService:
    """작업 간 의존성과 재시도를 제어하는 일일 운영 파이프라인."""

    def __init__(self, session: Session) -> None:
        self._scheduler = SchedulerService(session)
        self._repository = PipelineRepository(session)

    async def execute(
        self,
        *,
        pipeline_name: str,
        trigger_type: str,
        request_payload: dict[str, Any],
        steps: list[PipelineStepDefinition],
    ):
        pipeline = self._repository.create_pipeline(
            pipeline_name=pipeline_name,
            trigger_type=trigger_type.upper(),
            request_payload=request_payload,
        )

        step_results: list[dict[str, Any]] = []

        try:
            for definition in sorted(
                steps,
                key=lambda item: item.step_order,
            ):
                step_entity = self._repository.create_step(
                    pipeline_run_id=pipeline.pipeline_run_id,
                    step_order=definition.step_order,
                    step_name=definition.step_name,
                    job_name=definition.job_name,
                )

                result = await self._execute_step(
                    step_entity=step_entity,
                    definition=definition,
                )
                step_results.append(result)

            completed = self._repository.complete_pipeline(
                entity=pipeline,
                status_code="SUCCESS",
                finished_at=datetime.now(timezone.utc),
                result_payload={"steps": step_results},
                error_message=None,
            )

            return completed, step_results

        except Exception as exc:
            failed = self._repository.complete_pipeline(
                entity=pipeline,
                status_code="FAILED",
                finished_at=datetime.now(timezone.utc),
                result_payload={"steps": step_results},
                error_message=str(exc)[:4000],
            )
            return failed, step_results

    async def _execute_step(
        self,
        *,
        step_entity,
        definition: PipelineStepDefinition,
    ) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        last_error: Exception | None = None

        for attempt in range(
            1,
            definition.max_attempts + 1,
        ):
            self._repository.update_step(
                entity=step_entity,
                status_code="RUNNING",
                attempt_count=attempt,
                started_at=started_at,
                finished_at=None,
                result_payload={},
                error_message=None,
            )

            try:
                history, result = await self._scheduler.execute(
                    job_name=definition.job_name,
                    payload=definition.payload,
                    trigger_type="PIPELINE",
                )

                payload = {
                    "job_run_id": history.job_run_id,
                    "status_code": history.status_code,
                    "result": result,
                }

                self._repository.update_step(
                    entity=step_entity,
                    status_code="SUCCESS",
                    attempt_count=attempt,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    result_payload=payload,
                    error_message=None,
                )

                return {
                    "step_name": definition.step_name,
                    "job_name": definition.job_name,
                    "status_code": "SUCCESS",
                    "attempt_count": attempt,
                    "result": payload,
                }

            except Exception as exc:
                last_error = exc

                if attempt < definition.max_attempts:
                    self._repository.update_step(
                        entity=step_entity,
                        status_code="RETRY_WAIT",
                        attempt_count=attempt,
                        started_at=started_at,
                        finished_at=None,
                        result_payload={},
                        error_message=str(exc)[:4000],
                    )
                    await asyncio.sleep(
                        definition.retry_delay_seconds
                    )
                    continue

                self._repository.update_step(
                    entity=step_entity,
                    status_code="FAILED",
                    attempt_count=attempt,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    result_payload={},
                    error_message=str(exc)[:4000],
                )

        assert last_error is not None
        raise last_error
