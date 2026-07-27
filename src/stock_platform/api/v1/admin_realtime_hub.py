"""STEP 8-5-9 — Admin / User Realtime Hub·Scope API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser, require_permission
from stock_platform.database.session import get_db_session
from stock_platform.realtime.market_data_hub import (
    get_realtime_market_data_hub,
)
from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)


admin_router = APIRouter(
    prefix="/api/v1/admin/realtime",
    tags=["Admin Realtime Hub"],
    dependencies=[Depends(require_admin)],
)

user_router = APIRouter(
    prefix="/api/v1/user/realtime",
    tags=["User Realtime"],
)


@admin_router.get("/connections")
def list_connections(
    _: AuthenticatedUser = Depends(require_admin),
):
    hub = get_realtime_market_data_hub()
    return {
        "items": [hub.status()],
        "health": hub.health_summary(),
    }


@admin_router.get("/subscriptions")
def list_subscriptions(
    _: AuthenticatedUser = Depends(require_admin),
):
    hub = get_realtime_market_data_hub()
    rows = hub.registry.list_subscriptions()
    return {"items": rows, "total": len(rows)}


@admin_router.get("/scopes")
def list_scopes(
    _: AuthenticatedUser = Depends(require_admin),
):
    hub = get_realtime_market_data_hub()
    rows = hub.registry.list_consumers()
    return {"items": rows, "total": len(rows)}


@admin_router.get("/scopes/{scope_key:path}")
def get_scope(
    scope_key: str,
    _: AuthenticatedUser = Depends(require_admin),
):
    hub = get_realtime_market_data_hub()
    row = hub.registry.get_consumer(scope_key)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "scope_not_found", "message": "Scope 없음"},
        )
    runtime = dynamic_strategy_runtime_manager.get_entry(scope_key)
    return {
        "consumer": row,
        "runtime": runtime.as_dict() if runtime else None,
    }


@admin_router.post("/scopes/{scope_key:path}/reconnect")
async def reconnect_scope(
    scope_key: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    """안전한 Hub dispatch 재시작 — 강제 주문/신호 없음."""

    hub = get_realtime_market_data_hub()
    if hub.registry.get_consumer(scope_key) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "scope_not_found", "message": "Scope 없음"},
        )
    await hub.stop_dispatch()
    result = await hub.start_dispatch()
    hub._reconnect_count = int(hub._reconnect_count) + 1
    audit.record(
        event_type="ADMIN_REALTIME_SCOPE_RECONNECT",
        actor=user.username or f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={"scope_key": scope_key[:120]},
    )
    return {"reconnected": True, "hub": result, "force_signal": False}


@admin_router.post("/scopes/{scope_key:path}/rewarm")
def rewarm_scope(
    scope_key: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    hub = get_realtime_market_data_hub()
    try:
        hub.registry.rewarm(scope_key)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "scope_not_found", "message": "Scope 없음"},
        ) from exc
    audit.record(
        event_type="ADMIN_REALTIME_SCOPE_REWARM",
        actor=user.username or f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={"scope_key": scope_key[:120]},
    )
    return {
        "rewarmed": True,
        "scope": hub.registry.get_consumer(scope_key),
        "force_signal": False,
    }


@user_router.get("/scopes")
def list_my_scopes(
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
):
    hub = get_realtime_market_data_hub()
    items = []
    for row in hub.registry.list_consumers():
        if int(row.get("user_id") or 0) != int(user.user_id):
            continue
        items.append(
            {
                "scope_key": row["scope_key"],
                "strategy_id": row["strategy_id"],
                "strategy_version": row["strategy_version"],
                "broker_code": row["broker_code"],
                "market_type": row["market_type"],
                "symbols": row["symbols"],
                "runtime_status": row["runtime_status"],
                "warmup_status": row["warmup_status"],
                "last_signal_at": row["last_signal_at"],
                "last_error": row["last_error"],
                "hub_connected": hub.status().get("dispatch_running"),
            }
        )
    return {"items": items, "total": len(items)}


@user_router.get("/scopes/{scope_key:path}")
def get_my_scope(
    scope_key: str,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    _ = session
    hub = get_realtime_market_data_hub()
    row = hub.registry.get_consumer(scope_key)
    if row is None or int(row.get("user_id") or 0) != int(user.user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "scope_not_found", "message": "Scope 없음"},
        )
    return {
        "scope_key": row["scope_key"],
        "strategy_id": row["strategy_id"],
        "strategy_version": row["strategy_version"],
        "symbols": row["symbols"],
        "runtime_status": row["runtime_status"],
        "warmup_status": row["warmup_status"],
        "last_signal_at": row["last_signal_at"],
        "last_error": row["last_error"],
        "hub_connected": hub.status().get("dispatch_running"),
    }
