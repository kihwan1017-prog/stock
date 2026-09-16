"""STEP 8-5-3 — ADMIN Recovery Scheduler API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.broker.recovery_scheduler import (
    broker_recovery_scheduler,
)
from stock_platform.broker.recovery_scheduler_service import (
    BrokerRecoverySchedulerService,
    RecoverySchedulerConfigError,
    job_entity_as_dict,
    run_recovery_scheduler_job,
)
from stock_platform.database.session import get_db_session
from stock_platform.operation.job_models import JobRunHistory
from sqlalchemy import select


router = APIRouter(
    prefix="/api/v1/admin/recovery/scheduler",
    tags=["Admin Recovery Scheduler"],
    dependencies=[Depends(require_admin)],
)


class JobUpdateBody(BaseModel):
    is_enabled: bool | None = None
    cron_expression: str | None = Field(default=None, max_length=80)
    interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    max_retries: int | None = Field(default=None, ge=0, le=20)
    backoff_base_seconds: int | None = Field(default=None, ge=1, le=3600)
    backoff_max_seconds: int | None = Field(default=None, ge=1, le=86400)
    concurrency: int | None = Field(default=None, ge=1, le=10)


def _http_config(exc: RecoverySchedulerConfigError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=str(exc),
    )


@router.get("/status")
def scheduler_status(
    _: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    runtime = broker_recovery_scheduler.status()
    jobs = [
        job_entity_as_dict(j)
        for j in BrokerRecoverySchedulerService(session).list_jobs()
    ]
    return {
        **runtime,
        "jobs": jobs,
    }


@router.get("/jobs")
def list_scheduler_jobs(
    _: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    runtime = {
        j["job_id"]: j
        for j in broker_recovery_scheduler.status().get(
            "apscheduler_jobs", []
        )
    }
    items = []
    for row in BrokerRecoverySchedulerService(session).list_jobs():
        data = job_entity_as_dict(row)
        aps = runtime.get(row.job_id) or {}
        if aps.get("next_run_at"):
            data["next_run_at"] = aps["next_run_at"]
        items.append(data)
    return {"items": items, "total": len(items)}


@router.put("/jobs/{job_id}")
def update_scheduler_job(
    job_id: str,
    body: JobUpdateBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    svc = BrokerRecoverySchedulerService(session)
    try:
        before = job_entity_as_dict(svc.require_job(job_id))
        row = svc.update_job(
            job_id,
            body.model_dump(exclude_unset=True),
            actor=f"admin:{user.user_id}",
        )
        session.commit()
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except RecoverySchedulerConfigError as exc:
        raise _http_config(exc) from exc

    broker_recovery_scheduler.reload()
    after = job_entity_as_dict(row)
    audit.record(
        event_type="RECOVERY_SCHEDULER_JOB_UPDATE",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "job_id": job_id,
            "before": {
                k: before.get(k)
                for k in (
                    "is_enabled",
                    "cron_expression",
                    "interval_minutes",
                    "timeout_seconds",
                    "max_retries",
                    "concurrency",
                )
            },
            "after": {
                k: after.get(k)
                for k in (
                    "is_enabled",
                    "cron_expression",
                    "interval_minutes",
                    "timeout_seconds",
                    "max_retries",
                    "concurrency",
                )
            },
        },
    )
    return after


@router.post("/jobs/{job_id}/enable")
def enable_job(
    job_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    return _set_enabled(
        job_id,
        enabled=True,
        request=request,
        user=user,
        session=session,
        audit=audit,
    )


@router.post("/jobs/{job_id}/disable")
def disable_job(
    job_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    return _set_enabled(
        job_id,
        enabled=False,
        request=request,
        user=user,
        session=session,
        audit=audit,
    )


def _set_enabled(
    job_id: str,
    *,
    enabled: bool,
    request: Request,
    user: AuthenticatedUser,
    session: Session,
    audit: AuditLogService,
) -> dict[str, Any]:
    svc = BrokerRecoverySchedulerService(session)
    try:
        row = svc.set_enabled(
            job_id, enabled=enabled, actor=f"admin:{user.user_id}"
        )
        session.commit()
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    broker_recovery_scheduler.reload()
    audit.record(
        event_type=(
            "RECOVERY_SCHEDULER_JOB_ENABLE"
            if enabled
            else "RECOVERY_SCHEDULER_JOB_DISABLE"
        ),
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={"job_id": job_id, "is_enabled": enabled},
    )
    return job_entity_as_dict(row)


@router.post("/jobs/{job_id}/run")
async def run_job_now(
    job_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    svc = BrokerRecoverySchedulerService(session)
    try:
        svc.require_job(job_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    audit.record(
        event_type="RECOVERY_SCHEDULER_JOB_RUN_NOW",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={"job_id": job_id},
    )
    session.commit()

    try:
        result = await run_recovery_scheduler_job(
            job_id,
            trigger_type="ADMIN_MANUAL",
            requested_by=f"admin:{user.user_id}",
            force=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return result


@router.get("/runs")
def list_scheduler_runs(
    limit: int = 50,
    offset: int = 0,
    _: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    stmt = (
        select(JobRunHistory)
        .where(JobRunHistory.job_group == "RECOVERY")
        .order_by(JobRunHistory.job_run_id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list(session.scalars(stmt))
    return {
        "items": [
            {
                "job_run_id": int(r.job_run_id),
                "job_name": r.job_name,
                "job_group": r.job_group,
                "trigger_type": r.trigger_type,
                "status_code": r.status_code,
                "started_at": (
                    r.started_at.isoformat() if r.started_at else None
                ),
                "finished_at": (
                    r.finished_at.isoformat() if r.finished_at else None
                ),
                "duration_ms": r.duration_ms,
                "result_payload": r.result_payload,
                "error_message": r.error_message,
            }
            for r in rows
        ],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }
