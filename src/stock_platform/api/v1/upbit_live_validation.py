"""STEP 8-9 — Admin/User Upbit Live Validation API."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import AuthenticatedUser, require_admin, require_permission
from stock_platform.database.session import get_db_session
from stock_platform.trading.upbit_live_smoke_constants import (
    CONFIRMATION_TEXT,
    MAX_SMOKE_AMOUNT,
)
from stock_platform.trading.upbit_live_smoke_service import (
    UpbitLiveSmokeError,
    UpbitLiveSmokeService,
)
from stock_platform.trading.upbit_live_preflight_service import (
    UpbitLivePreflightService,
)

admin_router = APIRouter(
    prefix="/api/v1/admin/live-validation/upbit",
    tags=["Admin Upbit Live Validation"],
    dependencies=[Depends(require_admin)],
)

user_router = APIRouter(
    prefix="/api/v1/user/live-validation/upbit",
    tags=["User Upbit Live Validation"],
)


class PreflightRequest(BaseModel):
    user_broker_account_id: int = Field(ge=1)
    market: str = Field(min_length=3, max_length=30)
    side: str = Field(min_length=3, max_length=4)
    amount: Decimal = Field(gt=0)
    limit_price: Decimal = Field(gt=0)
    arm_token: str | None = None


class ExecuteRequest(BaseModel):
    user_broker_account_id: int = Field(ge=1)
    market: str = Field(min_length=3, max_length=30)
    side: str = Field(min_length=3, max_length=4)
    amount: Decimal = Field(gt=0)
    limit_price: Decimal = Field(gt=0)
    arm_token: str | None = None
    execute_live: bool = False
    confirmation_text: str | None = None
    preflight_id: str | None = None


@admin_router.post("/preflight")
def admin_preflight(
    body: PreflightRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    if body.amount > MAX_SMOKE_AMOUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AMOUNT_EXCEEDS_MAX",
        )
    if body.side.upper() not in {"BUY", "SELL"}:
        raise HTTPException(status_code=400, detail="INVALID_SIDE")
    result = UpbitLivePreflightService(session).run(
        user_broker_account_id=int(body.user_broker_account_id),
        market=body.market.upper(),
        side=body.side.upper(),
        amount=Decimal(str(body.amount)),
        limit_price=Decimal(str(body.limit_price)),
        arm_token=body.arm_token,
        actor=user.username,
        skip_live_network=False,
    )
    stored = UpbitLiveSmokeService(session).persist_preflight(
        preflight=result.to_dict(),
        actor=user.username,
    )
    session.commit()
    return stored


@admin_router.post("/execute")
def admin_execute(
    body: ExecuteRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    if body.amount > MAX_SMOKE_AMOUNT:
        raise HTTPException(status_code=400, detail="AMOUNT_EXCEEDS_MAX")
    if not body.execute_live:
        raise HTTPException(status_code=400, detail="EXECUTE_LIVE_REQUIRED")
    if not body.preflight_id:
        raise HTTPException(status_code=400, detail="PREFLIGHT_ID_REQUIRED")
    if body.confirmation_text != CONFIRMATION_TEXT:
        raise HTTPException(
            status_code=400, detail="CONFIRMATION_TEXT_MISMATCH"
        )
    try:
        result = UpbitLiveSmokeService(session).execute(
            user_broker_account_id=int(body.user_broker_account_id),
            market=body.market.upper(),
            side=body.side.upper(),
            amount=Decimal(str(body.amount)),
            limit_price=Decimal(str(body.limit_price)),
            actor=user.username,
            arm_token=body.arm_token,
            execute_live=bool(body.execute_live),
            confirmation_text=body.confirmation_text,
            preflight_id=body.preflight_id,
            skip_live_network=False,
        )
        session.commit()
        return result
    except UpbitLiveSmokeError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@admin_router.get("/runs")
def admin_list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    uba_id: int | None = None,
    session: Session = Depends(get_db_session),
):
    return {
        "items": UpbitLiveSmokeService(session).list_runs(
            limit=limit, uba_id=uba_id
        )
    }


@admin_router.get("/runs/{run_id}")
def admin_get_run(
    run_id: str,
    session: Session = Depends(get_db_session),
):
    try:
        return UpbitLiveSmokeService(session).get_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@admin_router.post("/runs/{run_id}/cancel")
def admin_cancel_run(
    run_id: str,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    """취소 요청 — Outbox CANCEL enqueue. 완료와 요청을 구분한다."""

    from sqlalchemy import select

    from stock_platform.trading.live_validation_entities import (
        LiveValidationRunEntity,
    )
    from stock_platform.trading.upbit_live_tracking_service import (
        UpbitLiveTrackingService,
    )

    row = session.scalar(
        select(LiveValidationRunEntity).where(
            LiveValidationRunEntity.run_id == run_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not row.order_id and not row.broker_order_uuid:
        raise HTTPException(status_code=400, detail="NO_ORDER")
    result = UpbitLiveTrackingService(session).request_cancel(
        row, actor=user.username, reason="ADMIN_CANCEL"
    )
    session.commit()
    return result


@admin_router.post("/runs/{run_id}/refresh")
def admin_refresh_run(
    run_id: str,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    """Broker 상태 새로고침 (Adapter 조회)."""

    from sqlalchemy import select

    from stock_platform.trading.live_validation_entities import (
        LiveValidationRunEntity,
    )
    from stock_platform.trading.upbit_live_tracking_service import (
        UpbitLiveTrackingService,
    )

    row = session.scalar(
        select(LiveValidationRunEntity).where(
            LiveValidationRunEntity.run_id == run_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    result = UpbitLiveTrackingService(session).refresh(
        row, actor=user.username
    )
    session.commit()
    return result


class ManualReviewRequest(BaseModel):
    evidence: str = Field(min_length=3, max_length=500)
    broker_status: str | None = None


@admin_router.post("/runs/{run_id}/manual-review")
def admin_manual_review(
    run_id: str,
    body: ManualReviewRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    from sqlalchemy import select

    from stock_platform.trading.live_validation_entities import (
        LiveValidationRunEntity,
    )
    from stock_platform.trading.upbit_live_tracking_service import (
        UpbitLiveTrackingService,
    )

    row = session.scalar(
        select(LiveValidationRunEntity).where(
            LiveValidationRunEntity.run_id == run_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    result = UpbitLiveTrackingService(session).complete_manual_review(
        row,
        actor=user.username,
        evidence=body.evidence,
        broker_status=body.broker_status,
    )
    session.commit()
    return result


@admin_router.get("/dashboard")
def admin_dashboard(session: Session = Depends(get_db_session)):
    from sqlalchemy import func, select

    from stock_platform.trading.live_validation_entities import (
        LiveValidationRunEntity,
    )
    from stock_platform.trading.upbit_live_tracking_scheduler import (
        upbit_live_tracking_scheduler,
    )

    def _count(status_col, value: str) -> int:
        return int(
            session.scalar(
                select(func.count())
                .select_from(LiveValidationRunEntity)
                .where(status_col == value)
            )
            or 0
        )

    return {
        "counts": {
            "outbox_pending": _count(
                LiveValidationRunEntity.internal_status, "OUTBOX_PENDING"
            ),
            "broker_submission_pending": _count(
                LiveValidationRunEntity.internal_status,
                "BROKER_SUBMISSION_PENDING",
            ),
            "open": _count(
                LiveValidationRunEntity.broker_order_status, "OPEN"
            ),
            "partial": _count(
                LiveValidationRunEntity.broker_order_status,
                "PARTIALLY_FILLED",
            ),
            "cancel_pending": _count(
                LiveValidationRunEntity.broker_order_status, "CANCEL_PENDING"
            ),
            "unknown": _count(
                LiveValidationRunEntity.broker_order_status, "UNKNOWN"
            ),
            "manual_review_required": int(
                session.scalar(
                    select(func.count())
                    .select_from(LiveValidationRunEntity)
                    .where(
                        LiveValidationRunEntity.manual_review_required.is_(
                            True
                        )
                    )
                )
                or 0
            ),
        },
        "tracker": upbit_live_tracking_scheduler.status(),
    }


@user_router.get("/runs")
def user_list_runs(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
    limit: int = Query(default=20, ge=1, le=100),
):
    """본인 UBA 실행 이력만 읽기 전용."""

    from stock_platform.trading.live_order_approval_service import (
        LiveOrderApprovalService,
    )

    accounts = LiveOrderApprovalService(session).list_for_user(
        int(user.user_id)
    )
    uba_ids = {int(a["user_broker_account_id"]) for a in accounts}
    items = UpbitLiveSmokeService(session).list_runs(limit=limit * 2)
    filtered = [
        i for i in items if int(i["user_broker_account_id"]) in uba_ids
    ][:limit]
    return {"items": filtered, "readonly": True}


@user_router.get("/runs/{run_id}")
def user_get_run(
    run_id: str,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    from stock_platform.trading.live_order_approval_service import (
        LiveOrderApprovalService,
    )

    try:
        row = UpbitLiveSmokeService(session).get_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    accounts = LiveOrderApprovalService(session).list_for_user(
        int(user.user_id)
    )
    uba_ids = {int(a["user_broker_account_id"]) for a in accounts}
    if int(row["user_broker_account_id"]) not in uba_ids:
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    return {**row, "readonly": True}


# confirmation text export for FE (상수만)
@admin_router.get("/meta")
def admin_meta():
    from stock_platform.trading.upbit_live_tracking_scheduler import (
        upbit_live_tracking_scheduler,
    )

    return {
        "confirmation_text_required": CONFIRMATION_TEXT,
        "max_amount": str(MAX_SMOKE_AMOUNT),
        "default_allowlist": ["KRW-BTC", "KRW-ETH", "KRW-XRP"],
        "order_type": "LIMIT_ONLY",
        "tracker": upbit_live_tracking_scheduler.status(),
    }
