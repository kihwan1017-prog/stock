"""Admin UPBIT Autotrading readiness / Live Outbox Worker 상태 (조회·link만)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.trading.autotrading_master_gate import (
    admin_set_uba_strategy_link_active,
    evaluate_uba_autotrading_ready,
)


router = APIRouter(
    prefix="/api/v1/admin/autotrading",
    tags=["Admin Autotrading Readiness"],
    dependencies=[Depends(require_admin)],
)


class StrategyLinkActiveBody(BaseModel):
    strategy_id: int = Field(..., ge=1)
    is_active: bool = True


@router.get("/uba/{user_broker_account_id}/readiness")
def admin_uba_autotrading_readiness(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """UBA 자동매매 Master Gate — 상태 조회만 (시작/주문 없음)."""

    return evaluate_uba_autotrading_ready(
        session, user_broker_account_id=int(user_broker_account_id)
    )


@router.get("/live-outbox-worker/status")
def admin_live_outbox_worker_status(
    _: AuthenticatedUser = Depends(require_admin),
):
    """LIVE Outbox Worker 상태. ENABLE은 env/settings — 이 API는 조회만."""

    from stock_platform.order.live_outbox_worker_runtime import (
        live_outbox_worker_runtime,
    )

    status_payload = live_outbox_worker_runtime.status()
    return {
        **status_payload,
        "enable_via": "LIVE_OUTBOX_WORKER_ENABLED settings/env",
        "note": (
            "ENABLE alone does not bypass LIVE/ARM/Activation; "
            "dispatch still Fail Closed"
        ),
        "mutate_allowed": False,
    }


@router.post("/uba/{user_broker_account_id}/strategy-link")
def admin_uba_strategy_link_set_active(
    user_broker_account_id: int,
    body: StrategyLinkActiveBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """승인된 Strategy link 활성/비활성. Runtime RUN·주문 전송 없음."""

    try:
        result = admin_set_uba_strategy_link_active(
            session,
            user_broker_account_id=int(user_broker_account_id),
            strategy_id=int(body.strategy_id),
            is_active=bool(body.is_active),
            actor=user.username,
        )
        session.commit()
        return result
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
