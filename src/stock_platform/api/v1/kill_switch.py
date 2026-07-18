from fastapi import (
    APIRouter,
    Depends,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.database.session import get_db_session
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)


router = APIRouter(
    prefix="/api/v1/risk/kill-switch",
    tags=["Risk Kill Switch"],
)


class KillSwitchActionRequest(BaseModel):
    actor: str = Field(
        min_length=1,
        max_length=100,
    )
    reason: str = Field(
        min_length=1,
        max_length=500,
    )


@router.get("")
def get_kill_switch_state(
    session: Session = Depends(get_db_session),
):
    return KillSwitchService(session).get_state()


@router.post("/activate")
def activate_kill_switch(
    request: KillSwitchActionRequest,
    _: str = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = KillSwitchService(session).activate(
        actor=request.actor,
        reason=request.reason,
    )
    audit.record(
        event_type="KILL_SWITCH_ACTIVATE",
        actor=request.actor,
        detail={"reason": request.reason},
    )
    return result


@router.post("/deactivate")
def deactivate_kill_switch(
    request: KillSwitchActionRequest,
    _: str = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = KillSwitchService(session).deactivate(
        actor=request.actor,
        reason=request.reason,
    )
    audit.record(
        event_type="KILL_SWITCH_DEACTIVATE",
        actor=request.actor,
        detail={"reason": request.reason},
    )
    return result
