from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.api.deps_admin import require_admin
from stock_platform.risk_engine.daily_loss_monitor import (
    DailyLossMonitor,
)
from stock_platform.risk_engine.daily_loss_runtime import (
    daily_loss_monitor_manager,
)
from stock_platform.risk_engine.risk_event_repository import (
    RiskEventRepository,
)
from stock_platform.risk_engine.runtime import (
    realtime_risk_policy,
)


router = APIRouter(
    prefix="/api/v1/risk/daily-loss",
    tags=["Daily Loss Monitor"],
    dependencies=[Depends(require_admin)],
)


class DailyLossResetRequest(BaseModel):
    actor: str = Field(
        min_length=1,
        max_length=100,
    )
    reason: str = Field(
        min_length=1,
        max_length=500,
    )


@router.get("/status")
def get_daily_loss_monitor_status():
    return daily_loss_monitor_manager.status()


@router.post("/check")
async def check_daily_loss_now():
    try:
        return await (
            daily_loss_monitor_manager.check_now()
        )
    except (
        ValueError,
        LookupError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/reset")
def reset_daily_loss_monitor(
    request: DailyLossResetRequest,
    account_number: str = Query(min_length=1),
    session: Session = Depends(get_db_session),
):
    return DailyLossMonitor(
        session=session,
        loss_limit=realtime_risk_policy.max_daily_loss,
    ).reset_daily_state(
        actor=request.actor,
        reason=request.reason,
    )


@router.get("/events")
def list_daily_loss_events(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
):
    return RiskEventRepository(
        session
    ).recent(limit=limit)
