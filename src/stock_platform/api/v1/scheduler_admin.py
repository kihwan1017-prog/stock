from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from stock_platform.scheduler.automatic import (
    AutomaticScheduler,
)


router = APIRouter(
    prefix="/api/v1/scheduler-admin",
    tags=["Scheduler Admin"],
)


@router.post("/run-now/{job_name}")
async def run_scheduled_job_now(job_name: str):
    try:
        return await AutomaticScheduler().run_job_now(
            job_name
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
