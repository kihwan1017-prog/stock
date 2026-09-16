"""STEP 8-5-14 — Admin Upbit Ambiguous Resolver Scheduler API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.broker.upbit.ambiguous_resolution_entities import (
    UpbitAmbiguousResolutionRunEntity,
)
from stock_platform.broker.upbit.ambiguous_resolution_scheduler import (
    upbit_ambiguous_order_resolution_scheduler,
)
from stock_platform.broker.upbit.ambiguous_resolution_service import (
    UpbitAmbiguousOrderResolutionService,
)
from stock_platform.broker.upbit.ambiguous_resolver import (
    UpbitAmbiguousOrderResolver,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session


admin_router = APIRouter(
    prefix="/api/v1/admin/upbit/ambiguous-resolver",
    tags=["Admin Upbit Ambiguous Resolver"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get("/status")
def resolver_status(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    settings = get_settings()
    scheduler_state = upbit_ambiguous_order_resolution_scheduler.status()
    health = UpbitAmbiguousOrderResolver(session).health_summary()
    last_run = session.scalar(
        select(UpbitAmbiguousResolutionRunEntity).order_by(
            UpbitAmbiguousResolutionRunEntity
            .upbit_ambiguous_resolution_run_id.desc()
        )
    )
    return {
        "enabled": settings.upbit_ambiguous_resolver_enabled,
        "poll_seconds": settings.upbit_ambiguous_resolver_poll_seconds,
        "batch_size": settings.upbit_ambiguous_resolver_batch_size,
        "claim_seconds": settings.upbit_ambiguous_resolver_claim_seconds,
        "max_orders_per_account_per_run": (
            settings.upbit_ambiguous_max_orders_per_account_per_run
        ),
        "lookup_max_interval_seconds": (
            settings.upbit_ambiguous_lookup_max_interval_seconds
        ),
        "auto_resubmit_enabled": (
            settings.upbit_order_auto_resubmit_enabled
        ),
        "scheduler": scheduler_state,
        "queue": health,
        "last_run": last_run.as_dict() if last_run else None,
    }


@admin_router.get("/runs")
def list_runs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    stmt = (
        select(UpbitAmbiguousResolutionRunEntity)
        .order_by(
            UpbitAmbiguousResolutionRunEntity
            .upbit_ambiguous_resolution_run_id.desc()
        )
        .offset(offset)
        .limit(limit)
    )
    rows = list(session.scalars(stmt))
    return {
        "items": [r.as_dict() for r in rows],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }


@admin_router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    row = session.get(UpbitAmbiguousResolutionRunEntity, run_id)
    if row is None:
        raise HTTPException(404, detail="Run not found")
    return row.as_dict()


@admin_router.post("/run-now")
def run_now(
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    result = UpbitAmbiguousOrderResolutionService(session).run_once(
        trigger_type="ADMIN_MANUAL",
        requested_by=f"admin:{user.user_id}",
    )
    audit.record(
        event_type="ADMIN_UPBIT_AMBIGUOUS_RESOLVER_RUN_NOW",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "status": result.get("status"),
            "due_count": result.get("due_count"),
            "claimed_count": result.get("claimed_count"),
        },
    )
    session.commit()
    return result
