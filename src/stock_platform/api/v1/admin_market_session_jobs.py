"""STEP 8-5-15 — Admin Persistent Market Session Jobs API."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.operation.market_session_job_dispatcher import (
    market_session_job_dispatcher,
)
from stock_platform.operation.market_session_job_reconcile import (
    MarketSessionJobReconciliationService,
)
from stock_platform.operation.market_session_job_service import (
    MarketSessionJobError,
    MarketSessionJobService,
    job_as_dict,
)

admin_router = APIRouter(
    prefix="/api/v1/admin/market-session-jobs",
    tags=["Admin Market Session Jobs"],
    dependencies=[Depends(require_admin)],
)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ReconcileBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    exchange_code: str = "KRX"
    days_ahead: int | None = Field(default=None, ge=0, le=60)


def _raise_error(exc: MarketSessionJobError) -> None:
    http = status.HTTP_400_BAD_REQUEST
    if exc.code == "not_found":
        http = status.HTTP_404_NOT_FOUND
    elif exc.code in {"busy", "claim_failed"}:
        http = status.HTTP_409_CONFLICT
    raise HTTPException(status_code=http, detail=exc.message)


@admin_router.get("")
def list_jobs(
    exchange_code: str | None = Query(None),
    market_date: date | None = Query(None),
    status_code: str | None = Query(None),
    job_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    rows = MarketSessionJobService(session).list_jobs(
        exchange_code=exchange_code,
        market_date=market_date,
        status_code=status_code,
        job_type=job_type,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [job_as_dict(r) for r in rows],
        "count": len(rows),
        "limit": limit,
        "offset": offset,
    }


@admin_router.get("/health")
def health(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    summary = MarketSessionJobService(session).health_summary()
    summary["dispatcher"] = {
        "instance_id": market_session_job_dispatcher.instance_id,
    }
    try:
        from stock_platform.operation.market_session_job_scheduler import (
            market_session_job_scheduler,
        )

        summary["scheduler"] = market_session_job_scheduler.status()
    except Exception:  # noqa: BLE001
        summary["scheduler"] = None
    return summary


@admin_router.post("/reconcile")
def reconcile(
    body: ReconcileBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    result = MarketSessionJobReconciliationService(session).reconcile(
        exchange_code=body.exchange_code,
        days_ahead=body.days_ahead,
    )
    audit.record(
        event_type="ADMIN_MARKET_SESSION_JOB_RECONCILE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "reason": body.reason,
            "checked_days": result.get("checked_days"),
            "created": result.get("created"),
            "expired_claims": result.get("expired_claims"),
        },
    )
    session.commit()
    return result


@admin_router.get("/{job_id}")
def get_job(
    job_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    row = MarketSessionJobService(session).get(job_id)
    if row is None:
        raise HTTPException(404, detail="Job not found")
    return job_as_dict(row)


@admin_router.get("/{job_id}/runs")
def get_job_runs(
    job_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    svc = MarketSessionJobService(session)
    if svc.get(job_id) is None:
        raise HTTPException(404, detail="Job not found")
    rows = svc.list_runs(job_id)
    return {"items": [r.as_dict() for r in rows], "count": len(rows)}


@admin_router.post("/{job_id}/run-now")
async def run_now(
    job_id: int,
    body: ReasonBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = await market_session_job_dispatcher.run_now(
            job_id, actor=user.username
        )
    except MarketSessionJobError as exc:
        _raise_error(exc)
        return
    audit.record(
        event_type="ADMIN_MARKET_SESSION_JOB_RUN_NOW",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "job_id": job_id,
            "reason": body.reason,
            "status": result.get("status"),
        },
    )
    return result


@admin_router.post("/{job_id}/retry")
def retry_job(
    job_id: int,
    body: ReasonBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    try:
        result = MarketSessionJobService(session).retry_job(
            job_id, actor=user.username, reason=body.reason
        )
    except MarketSessionJobError as exc:
        _raise_error(exc)
        return
    audit.record(
        event_type="ADMIN_MARKET_SESSION_JOB_RETRY",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={"job_id": job_id, "reason": body.reason},
    )
    return result


@admin_router.post("/{job_id}/cancel")
def cancel_job(
    job_id: int,
    body: ReasonBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    try:
        result = MarketSessionJobService(session).cancel_job(
            job_id, actor=user.username, reason=body.reason
        )
    except MarketSessionJobError as exc:
        _raise_error(exc)
        return
    audit.record(
        event_type="ADMIN_MARKET_SESSION_JOB_CANCEL",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={"job_id": job_id, "reason": body.reason},
    )
    return result


@admin_router.post("/{job_id}/release-stale-claim")
def release_stale_claim(
    job_id: int,
    body: ReasonBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    result = MarketSessionJobService(session).release_stale_claim(
        job_id, actor=user.username
    )
    audit.record(
        event_type="ADMIN_MARKET_SESSION_JOB_RELEASE_STALE_CLAIM",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "job_id": job_id,
            "reason": body.reason,
            "status": result.get("status"),
        },
    )
    return result
