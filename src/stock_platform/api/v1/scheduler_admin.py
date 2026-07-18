from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.scheduler.automatic import (
    AutomaticScheduler,
)


router = APIRouter(
    prefix="/api/v1/scheduler-admin",
    tags=["Scheduler Admin"],
)


@router.post("/run-now/{job_name}")
async def run_scheduled_job_now(
    job_name: str,
    _: str = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = await AutomaticScheduler().run_job_now(
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

    audit.record(
        event_type="SCHEDULER_RUN_NOW",
        actor="ADMIN",
        detail={"job_name": job_name},
    )
    return result
