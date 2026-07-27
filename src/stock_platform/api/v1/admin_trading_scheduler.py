"""STEP 9-5 — Admin Trading Scheduler Start/Pause (주문·Runner 미기동)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.trading.trading_scheduler_control_service import (
    TradingSchedulerControlError,
    TradingSchedulerControlService,
)

admin_router = APIRouter(
    prefix="/api/v1/admin/trading-scheduler",
    tags=["Admin Trading Scheduler"],
    dependencies=[Depends(require_admin)],
)


class SchedulerStartRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    correlation_id: str = Field(min_length=1, max_length=128)
    user_broker_account_id: int = Field(ge=1)
    min_arm_remaining_seconds: int = Field(default=120, ge=30, le=3600)


class SchedulerPauseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    correlation_id: str = Field(min_length=1, max_length=128)
    user_broker_account_id: int | None = Field(default=None, ge=1)


@admin_router.get("/status")
def admin_trading_scheduler_status(
    session: Session = Depends(get_db_session),
):
    return TradingSchedulerControlService(session).status()


@admin_router.post("/start")
async def admin_trading_scheduler_start(
    body: SchedulerStartRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """Trading Scheduler만 START. Runtime/Strategy/주문 미기동. LIVE/ARM 미변경."""
    service = TradingSchedulerControlService(session)
    try:
        result = service.start(
            actor=user.username,
            reason=body.reason,
            correlation_id=body.correlation_id,
            user_broker_account_id=body.user_broker_account_id,
            min_arm_remaining_seconds=body.min_arm_remaining_seconds,
            enforce_gates=True,
        )
        session.commit()
    except TradingSchedulerControlError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    if result.get("already_running"):
        return result

    audit.record(
        event_type="TRADING_SCHEDULER_STARTED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "actor_role": "ADMIN",
            "user_broker_account_id": body.user_broker_account_id,
            "broker_code": (result.get("gate") or {}).get("broker_code"),
            "user_id": (result.get("gate") or {}).get("user_id"),
            "previous_desired": result.get("previous_desired"),
            "previous_actual": result.get("previous_actual"),
            "new_desired": result.get("desired_state"),
            "new_actual": result.get("actual_state"),
            "live": True,
            "arm": True,
            "arm_expires_at": (result.get("gate") or {}).get(
                "arm_expires_at"
            ),
            "runtime": "paused",
            "active_strategy_count": 0,
            "reason": body.reason,
            "correlation_id": body.correlation_id,
        },
    )
    session.commit()
    return result


@admin_router.post("/pause")
async def admin_trading_scheduler_pause(
    body: SchedulerPauseRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """비상 Pause — LIVE/ARM/Runtime 미변경."""
    service = TradingSchedulerControlService(session)
    try:
        result = service.pause(
            actor=user.username,
            reason=body.reason,
            correlation_id=body.correlation_id,
            user_broker_account_id=body.user_broker_account_id,
            require_correlation_id=True,
        )
        session.commit()
    except TradingSchedulerControlError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    if result.get("already_paused"):
        return result

    audit.record(
        event_type="TRADING_SCHEDULER_PAUSED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "actor_role": "ADMIN",
            "reason": body.reason,
            "correlation_id": body.correlation_id,
            "user_broker_account_id": body.user_broker_account_id,
            "new_desired": "PAUSE",
            "new_actual": result.get("actual_state"),
        },
    )
    session.commit()
    return result
