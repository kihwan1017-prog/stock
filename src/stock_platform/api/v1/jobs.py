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


@router.get("")
def list_registered_jobs(
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
    session: Session = Depends(get_db_session),
):
    try:
        history, result = await SchedulerService(
            session
        ).execute(
            job_name=job_name,
            payload=request.payload,
            trigger_type=request.trigger_type,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "job_run_id": history.job_run_id,
        "job_name": history.job_name,
        "job_group": history.job_group,
        "trigger_type": history.trigger_type,
        "status_code": history.status_code,
        "started_at": history.started_at,
        "finished_at": history.finished_at,
        "duration_ms": history.duration_ms,
        "result": result,
    }


@router.get("/history")
def list_job_history(
    job_name: str | None = None,
    status_code: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_db_session),
):
    return JobRunRepository(session).list_recent(
        job_name=job_name,
        status_code=status_code,
        limit=limit,
    )
