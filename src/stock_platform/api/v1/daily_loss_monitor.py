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
    session: Session = Depends(get_db_session),
):
    return DailyLossMonitor(
        session=session,
        loss_limit=realtime_risk_policy.max_daily_loss,
    ).reset_daily_state(
        actor=request.actor,
        reason=request.reason,
    )


@router.get("/strategy-owned")
def get_strategy_owned_daily_pnl(
    user_broker_account_id: int = Query(..., ge=1),
    strategy_id: int = Query(..., ge=1),
    deployment_id: int | None = Query(default=None),
    broker_code: str = Query(default="KIWOOM"),
    session: Session = Depends(get_db_session),
):
    """Account Safety vs Strategy-owned Daily PnL 분리 조회."""

    from decimal import Decimal

    from stock_platform.risk_engine.daily_loss_entities import (
        AccountDailyLossEntity,
    )
    from stock_platform.risk_engine.resolved_policy import (
        ResolvedRiskPolicyResolver,
    )
    from stock_platform.risk_engine.strategy_owned_risk_service import (
        StrategyOwnedRiskService,
    )
    from sqlalchemy import select
    from datetime import datetime
    from zoneinfo import ZoneInfo

    policy = ResolvedRiskPolicyResolver(session).resolve(
        user_id=None,
        user_broker_account_id=user_broker_account_id,
    )
    limit = Decimal(str(policy.daily_max_loss_amount))
    svc = StrategyOwnedRiskService(session)
    strategy = svc.compute_and_persist(
        user_broker_account_id=user_broker_account_id,
        broker_code=broker_code,
        strategy_id=strategy_id,
        deployment_id=deployment_id,
        loss_limit=limit,
    )
    hard_block, hard_detail = svc.account_hard_safety_blocks_entry(
        user_broker_account_id=user_broker_account_id,
    )
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    account_row = session.scalar(
        select(AccountDailyLossEntity).where(
            AccountDailyLossEntity.user_broker_account_id
            == user_broker_account_id,
            AccountDailyLossEntity.trading_date == today,
        )
    )
    session.commit()
    return {
        "account_safety": {
            "current_loss_amount": (
                str(account_row.current_loss_amount)
                if account_row is not None
                else None
            ),
            "status_code": (
                account_row.status_code if account_row is not None else None
            ),
            "hard_safety_blocks_entry": hard_block,
            "hard_safety_detail": hard_detail,
            "note": (
                "Account MTM drawdown is telemetry; "
                "Strategy ENTRY uses strategy-owned PnL"
            ),
        },
        "strategy_autotrading": strategy.to_dict(),
        "strategy_daily_loss_limit": str(limit),
        "strategy_entry_gate": (
            "BLOCK"
            if hard_block or strategy.current_loss_amount >= limit
            else "PASS"
        ),
    }


@router.get("/events")
def list_daily_loss_events(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
):
    return RiskEventRepository(
        session
    ).recent(limit=limit)
