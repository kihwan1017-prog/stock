"""STEP 8-4 — 관리자 Recovery API (통합 Runtime)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.broker.recovery_repository import (
    BrokerRecoveryRepository,
)
from stock_platform.broker.recovery_runtime import (
    broker_recovery_manager,
)
from stock_platform.broker.recovery_distributed_lock import (
    build_distributed_lock_manager_from_settings,
)
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/admin/recovery",
    tags=["Admin Recovery"],
    dependencies=[Depends(require_admin)],
)


def _raise_if_single_account_busy(result: dict) -> None:
    """단일 계좌 Recovery가 분산 Lock Busy면 409."""

    accounts = result.get("accounts") or []
    if len(accounts) != 1:
        return
    row = accounts[0] or {}
    if row.get("status") != "SKIPPED_DISTRIBUTED_LOCK":
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "RECOVERY_LOCK_BUSY",
            "message": "Recovery is already running on another instance",
            "lock_scope_key": row.get("lock_scope_key"),
            "owner_masked": row.get("owner_masked"),
            "lease_expires_at": row.get("lease_expires_at"),
        },
    )


class RecoveryRunBody(BaseModel):
    broker_code: str | None = None
    paper_account_id: int | None = Field(default=None, gt=0)
    user_broker_account_id: int | None = Field(default=None, gt=0)
    concurrency: int = Field(default=3, ge=1, le=10)


@router.get("/status")
def get_recovery_status(
    _: AuthenticatedUser = Depends(require_admin),
):
    return broker_recovery_manager.status()


@router.post("/paper-fill/stalled")
def recover_stalled_paper_fills(
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """ACCEPTED Paper TradingOrder auto-fill 재시도."""

    from stock_platform.order.paper_fill_recovery import (
        recover_stalled_paper_accepted_orders,
    )

    return recover_stalled_paper_accepted_orders(
        session, limit=limit
    )


@router.get("/runs")
def list_recovery_runs(
    broker_code: str | None = None,
    status_code: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    rows = BrokerRecoveryRepository(session).list_runs(
        broker_code=broker_code,
        status_code=status_code,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [
            {
                "broker_recovery_run_id": int(r.broker_recovery_run_id),
                "status_code": r.status_code,
                "trigger_type": r.trigger_type,
                "broker_code": r.broker_code,
                "user_id": r.user_id,
                "paper_account_id": r.paper_account_id,
                "user_broker_account_id": r.user_broker_account_id,
                "requested_by": r.requested_by,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "open_orders_checked": r.open_orders_checked,
                "orders_updated": r.orders_updated,
                "fills_created": r.fills_created,
                "balances_updated": r.balances_updated,
                "positions_updated": r.positions_updated,
                "conflicts_found": r.conflicts_found,
                "error_message": r.error_message,
            }
            for r in rows
        ]
    }


@router.get("/runs/{recovery_id}")
def get_recovery_run(
    recovery_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    row = BrokerRecoveryRepository(session).get_run(recovery_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Recovery run not found")
    payload = dict(row.result_payload or {})
    for key in list(payload.keys()):
        if any(
            s in key.lower()
            for s in ("secret", "token", "key", "password", "account_number")
        ):
            payload[key] = "***"
    return {
        "broker_recovery_run_id": int(row.broker_recovery_run_id),
        "status_code": row.status_code,
        "trigger_type": row.trigger_type,
        "broker_code": row.broker_code,
        "user_id": row.user_id,
        "paper_account_id": row.paper_account_id,
        "user_broker_account_id": row.user_broker_account_id,
        "requested_by": row.requested_by,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "open_orders_checked": row.open_orders_checked,
        "orders_updated": row.orders_updated,
        "fills_created": row.fills_created,
        "balances_updated": row.balances_updated,
        "positions_updated": row.positions_updated,
        "conflicts_found": row.conflicts_found,
        "error_message": row.error_message,
        "result_payload": payload,
    }


@router.post("/run")
async def run_recovery(
    body: RecoveryRunBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    try:
        result = await broker_recovery_manager.recover_all(
            trigger_type="MANUAL",
            broker_code=body.broker_code,
            paper_account_id=body.paper_account_id,
            user_broker_account_id=body.user_broker_account_id,
            requested_by=user.username,
            concurrency=body.concurrency,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    audit.record(
        event_type="ADMIN_RECOVERY_RUN",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "broker_code": body.broker_code,
            "paper_account_id": body.paper_account_id,
            "user_broker_account_id": body.user_broker_account_id,
            "success": result.get("success"),
            "account_count": result.get("account_count"),
        },
    )
    session.commit()
    return result


@router.post("/accounts/{account_id}/run")
async def run_account_recovery(
    account_id: int,
    http_request: Request,
    account_type: str = Query(default="PAPER"),
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    kind = (account_type or "PAPER").upper()
    try:
        if kind == "PAPER":
            result = await broker_recovery_manager.recover_all(
                trigger_type="MANUAL",
                paper_account_id=account_id,
                requested_by=user.username,
            )
        else:
            result = await broker_recovery_manager.recover_all(
                trigger_type="MANUAL",
                user_broker_account_id=account_id,
                broker_code=kind if kind in {"KIWOOM", "UPBIT"} else None,
                requested_by=user.username,
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    _raise_if_single_account_busy(result)
    audit.record(
        event_type="ADMIN_RECOVERY_ACCOUNT_RUN",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "account_id": account_id,
            "account_type": kind,
            "success": result.get("success"),
        },
    )
    session.commit()
    return result


@router.get("/locks")
def list_recovery_locks(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    _: AuthenticatedUser = Depends(require_admin),
):
    """분산 Lock 목록 (Owner 마스킹, Secret 미포함)."""

    mgr = build_distributed_lock_manager_from_settings()
    items = mgr.list_locks(status=status_filter, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/locks/{scope_key}")
def get_recovery_lock(
    scope_key: str,
    _: AuthenticatedUser = Depends(require_admin),
):
    mgr = build_distributed_lock_manager_from_settings()
    row = mgr.get_lock(scope_key)
    if row is None:
        raise HTTPException(status_code=404, detail="Lock not found")
    return row


@router.post("/brokers/{broker_code}/run")
async def run_broker_code_recovery(
    broker_code: str,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    try:
        result = await broker_recovery_manager.recover_all(
            trigger_type="MANUAL",
            broker_code=broker_code.upper(),
            requested_by=user.username,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    audit.record(
        event_type="ADMIN_RECOVERY_BROKER_RUN",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "broker_code": broker_code.upper(),
            "success": result.get("success"),
            "account_count": result.get("account_count"),
        },
    )
    session.commit()
    return result
