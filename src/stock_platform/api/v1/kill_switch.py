from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import require_authenticated
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
    # 선택: UPBIT/KRX 등 — reason에 EXCHANGES= 토큰으로 기록
    exchange_codes: list[str] | None = Field(
        default=None,
        max_length=20,
    )


@router.get("")
def get_kill_switch_state(
    _: str = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
):
    # 조회는 로그인 사용자(또는 Admin Key)에게 허용 — User Web 대시보드용
    return KillSwitchService(session).get_state()


@router.get("/history")
def get_kill_switch_history(
    limit: int = Query(default=50, ge=1, le=200),
    _: str = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    """Kill Switch 활성화/해제 감사 이력."""

    rows = KillSwitchService(session).list_history(
        limit=limit
    )
    return [
        {
            "kill_switch_history_id": row.kill_switch_history_id,
            "scope_code": row.scope_code,
            "action_code": row.action_code,
            "reason": row.reason,
            "actor": row.actor,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/activate")
async def activate_kill_switch(
    request: KillSwitchActionRequest,
    _: str = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = KillSwitchService(session).activate(
        actor=request.actor,
        reason=request.reason,
        exchange_codes=request.exchange_codes,
    )
    # STEP 8-5-5 — 시스템 Kill Switch는 전체 Scope Runtime Pause
    try:
        from stock_platform.strategy_deployment.runtime_manager import (
            dynamic_strategy_runtime_manager,
        )

        paused = await dynamic_strategy_runtime_manager.pause_all(
            reason="kill_switch"
        )
    except Exception:  # noqa: BLE001
        paused = 0

    audit.record(
        event_type="KILL_SWITCH_ACTIVATE",
        actor=request.actor,
        detail={
            "reason": result.reason,
            "exchange_scope": list(result.exchange_scope),
            "runtimes_paused": paused,
        },
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
