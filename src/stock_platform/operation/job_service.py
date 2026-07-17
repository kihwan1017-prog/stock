from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from time import perf_counter
from typing import Any, TypeVar

from stock_platform.operation.job_repository import (
    JobRunRepository,
)


T = TypeVar("T")


class JobExecutionService:
    """작업 실행 전후 상태와 결과를 operation.job_run_history에 기록한다."""

    def __init__(
        self,
        repository: JobRunRepository,
    ) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        job_name: str,
        job_group: str,
        trigger_type: str,
        request_payload: dict[str, Any],
        handler: Callable[[], T | Awaitable[T]],
    ) -> tuple[Any, Any]:
        entity = self._repository.create(
            job_name=job_name,
            job_group=job_group,
            trigger_type=trigger_type,
            request_payload=request_payload,
        )

        started = perf_counter()

        try:
            result = handler()
            if inspect.isawaitable(result):
                result = await result

            duration_ms = int(
                (perf_counter() - started) * 1000
            )

            result_payload = self._normalize_result(result)

            completed = self._repository.complete(
                entity=entity,
                status_code="SUCCESS",
                finished_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
                result_payload=result_payload,
                error_message=None,
            )

            return completed, result

        except Exception as exc:
            duration_ms = int(
                (perf_counter() - started) * 1000
            )

            self._repository.complete(
                entity=entity,
                status_code="FAILED",
                finished_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
                result_payload={},
                error_message=str(exc)[:4000],
            )
            raise

    @staticmethod
    def _normalize_result(result: Any) -> dict[str, Any]:
        if result is None:
            return {}

        if isinstance(result, dict):
            return JobExecutionService._json_safe(result)

        if is_dataclass(result) and not isinstance(result, type):
            return JobExecutionService._json_safe(asdict(result))

        if hasattr(result, "to_dict") and callable(result.to_dict):
            return JobExecutionService._json_safe(result.to_dict())

        if hasattr(result, "__dict__"):
            return JobExecutionService._json_safe(
                {
                    key: value
                    for key, value in vars(result).items()
                    if not key.startswith("_")
                }
            )

        return {"value": str(result)}

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: JobExecutionService._json_safe(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple)):
            return [
                JobExecutionService._json_safe(item)
                for item in value
            ]

        if isinstance(value, (datetime, date)):
            return value.isoformat()

        if isinstance(value, Decimal):
            return str(value)

        return value
