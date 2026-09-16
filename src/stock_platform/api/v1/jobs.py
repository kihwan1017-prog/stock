from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.operation.job_repository import (
    JobRunRepository,
)
from stock_platform.scheduler.service import (
    SchedulerService,
)


router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["Jobs"],
)


class JobExecutionRequest(BaseModel):
    payload: dict[str, Any] = Field(
        default_factory=dict
    )
    trigger_type: str = Field(
        default="MANUAL",
        min_length=1,
        max_length=30,
    )


def _job_history_dict(row) -> dict[str, Any]:
    return {
        "job_run_id": row.job_run_id,
        "job_name": row.job_name,
        "job_group": row.job_group,
        "trigger_type": row.trigger_type,
        "status_code": row.status_code,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "duration_ms": row.duration_ms,
        "error_message": row.error_message,
        "request_payload": row.request_payload,
        "result_payload": row.result_payload,
    }


@router.get("")
def list_registered_jobs(
    _: str = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    jobs = SchedulerService(session).list_jobs()

    return [
        {
            "name": job.name,
            "group": job.group,
            "description": job.description,
        }
        for job in jobs
    ]


@router.post("/{job_name}/execute")
async def execute_job(
    job_name: str,
    request: JobExecutionRequest,
    _: AuthenticatedUser = Depends(
        require_permission("ops:execute")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        history, result = await SchedulerService(
            session
        ).execute(
            job_name=job_name.strip(),
            payload=request.payload,
            trigger_type=request.trigger_type,
        )
    except LookupError as exc:
        detail = str(exc)
        # KeyError도 LookupError 하위 — 필수 payload 누락은 400
        if isinstance(exc, KeyError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"필수 payload 필드 누락: {detail}",
            ) from exc
        # 미등록 잡만 404, 선행 데이터 부족 등은 409
        if detail.startswith("Job not found:"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=detail,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        **_job_history_dict(history),
        "result": result,
    }


@router.get("/history")
def list_job_history(
    job_name: str | None = None,
    status_code: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _: str = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    rows = JobRunRepository(session).list_recent(
        job_name=job_name,
        status_code=status_code,
        limit=limit,
    )
    return {
        "items": [_job_history_dict(row) for row in rows],
        "limit": limit,
    }
