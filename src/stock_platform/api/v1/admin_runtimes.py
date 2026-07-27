"""STEP 8-5-5 — Strategy Runtime ADMIN API (Scope 필수)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.strategy_deployment.runtime_manager import (
    RuntimeScopeRequiredError,
    dynamic_strategy_runtime_manager,
)


router = APIRouter(
    prefix="/api/v1/admin/runtimes",
    tags=["Admin Strategy Runtimes"],
    dependencies=[Depends(require_admin)],
)


class NoteBody(BaseModel):
    reason: str = Field(default="admin", max_length=500)


@router.get("")
def list_admin_runtimes(
    user_id: int | None = None,
    strategy_id: int | None = None,
    _: AuthenticatedUser = Depends(require_admin),
):
    entries = dynamic_strategy_runtime_manager.list_entries(
        user_id=user_id,
        strategy_id=strategy_id,
    )
    return {
        "items": [e.as_dict() for e in entries],
        "total": len(entries),
        "global_slot_removed": True,
    }


@router.get("/status")
def admin_runtime_registry_status(
    _: AuthenticatedUser = Depends(require_admin),
):
    return dynamic_strategy_runtime_manager.status()


@router.get("/{scope_key:path}")
def get_admin_runtime(
    scope_key: str,
    _: AuthenticatedUser = Depends(require_admin),
):
    entry = dynamic_strategy_runtime_manager.get_entry(scope_key)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runtime not found",
        )
    return entry.as_dict()


@router.post("/{scope_key:path}/pause")
async def pause_admin_runtime(
    scope_key: str,
    body: NoteBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        entry = await dynamic_strategy_runtime_manager.pause_runtime(
            scope_key, reason=body.reason or "admin_pause"
        )
    except (LookupError, RuntimeScopeRequiredError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    audit.record(
        event_type="STRATEGY_RUNTIME_PAUSE",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "scope_key": scope_key,
            "reason": body.reason,
            "status": entry.status.value,
        },
    )
    return entry.as_dict()


@router.post("/{scope_key:path}/resume")
async def resume_admin_runtime(
    scope_key: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        entry = await dynamic_strategy_runtime_manager.resume_runtime(
            scope_key
        )
    except (LookupError, RuntimeScopeRequiredError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    audit.record(
        event_type="STRATEGY_RUNTIME_RESUME",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={"scope_key": scope_key, "status": entry.status.value},
    )
    return entry.as_dict()


@router.post("/{scope_key:path}/reload")
async def reload_admin_runtime(
    scope_key: str,
    request: Request,
    force: bool = Query(default=True),
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = await dynamic_strategy_runtime_manager.reload(
            scope_key=scope_key, force=force
        )
    except (LookupError, RuntimeScopeRequiredError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    audit.record(
        event_type="STRATEGY_RUNTIME_RELOAD",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "scope_key": scope_key,
            "changed": getattr(result, "changed", None),
        },
    )
    return result


@router.post("/{scope_key:path}/stop")
async def stop_admin_runtime(
    scope_key: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        entry = await dynamic_strategy_runtime_manager.stop_runtime(
            scope_key
        )
    except (LookupError, RuntimeScopeRequiredError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    audit.record(
        event_type="STRATEGY_RUNTIME_STOP",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={"scope_key": scope_key},
    )
    return entry.as_dict()
