"""STEP 8-5-5 — Strategy Runtime ADMIN API (Scope 필수)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
)
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


class EnsureScopeBody(BaseModel):
    """활성 account_strategy_link → Scope 등록. start=False면 PAUSED만."""

    strategy_id: int = Field(..., ge=1)
    user_broker_account_id: int | None = Field(default=None, ge=1)
    paper_account_id: int | None = Field(default=None, ge=1)
    # RUNNING 금지 경로 — True는 resume API로만 허용
    start: bool = False


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


@router.post("/ensure-scope")
async def ensure_admin_runtime_scope(
    body: EnsureScopeBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """공식 initialize_scoped 경로로 Scope 등록.

    기본 start=False → PAUSED(게이트상 READY). Runner/주문 자동기동 없음.
    """

    if body.start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "START_NOT_ALLOWED",
                "message": (
                    "ensure-scope forbids start=true; "
                    "register PAUSED then use resume when armed"
                ),
            },
        )
    if (
        body.user_broker_account_id is None
        and body.paper_account_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "ACCOUNT_REQUIRED",
                "message": "uba or paper_account_id required",
            },
        )
    if (
        body.user_broker_account_id is not None
        and body.paper_account_id is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "ACCOUNT_AMBIGUOUS",
                "message": "provide only one of uba or paper",
            },
        )

    from stock_platform.risk_engine.kill_switch_service import (
        KillSwitchService,
    )
    from stock_platform.strategy_deployment.runtime_bootstrap import (
        _build_scope_for_link,
    )

    link_q = select(AccountStrategyLinkEntity).where(
        AccountStrategyLinkEntity.strategy_id == int(body.strategy_id),
        AccountStrategyLinkEntity.is_active.is_(True),
    )
    if body.user_broker_account_id is not None:
        link_q = link_q.where(
            AccountStrategyLinkEntity.user_broker_account_id
            == int(body.user_broker_account_id)
        )
    else:
        link_q = link_q.where(
            AccountStrategyLinkEntity.paper_account_id
            == int(body.paper_account_id)
        )
    link = session.scalars(link_q).first()
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "LINK_NOT_FOUND",
                "message": "active account_strategy_link not found",
            },
        )

    try:
        kill_active = bool(KillSwitchService(session).is_active())
    except Exception:  # noqa: BLE001
        kill_active = True
    try:
        scope, _suggested_start = _build_scope_for_link(
            session, link, kill_active=kill_active
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SCOPE_BUILD_FAILED", "message": str(exc)},
        ) from exc

    # 항상 PAUSED — RUNNING/주문/worker 자동 시작 없음
    result = await dynamic_strategy_runtime_manager.initialize_scoped(
        scope, force=True, start=False
    )
    entry = dynamic_strategy_runtime_manager.get_entry(scope.scope_key)
    payload = entry.as_dict() if entry is not None else {
        "scope_key": result.scope_key,
        "status": "PAUSED",
        "deployment_id": result.current_deployment_id,
    }
    audit.record(
        event_type="STRATEGY_RUNTIME_ENSURE_SCOPE",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "scope_key": scope.scope_key,
            "strategy_id": int(body.strategy_id),
            "user_broker_account_id": body.user_broker_account_id,
            "paper_account_id": body.paper_account_id,
            "start": False,
            "status": payload.get("status"),
            "deployment_id": payload.get("deployment_id"),
            "orders_started": False,
            "worker_started": False,
        },
    )
    return {
        "ensured": True,
        "start": False,
        "orders_started": False,
        "worker_started": False,
        "reload": {
            "changed": result.changed,
            "scope_key": result.scope_key,
            "deployment_id": result.current_deployment_id,
            "message": result.message,
        },
        "entry": payload,
    }


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
        # OPERATOR_PAUSE — watchdog/restore 자동 resume 금지 provenance
        entry = await dynamic_strategy_runtime_manager.pause_runtime(
            scope_key, reason=body.reason or "OPERATOR_PAUSE"
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
