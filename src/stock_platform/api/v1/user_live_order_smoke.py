"""사용자 Controlled Live Order Smoke API."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import AuthenticatedUser, require_permission
from stock_platform.database.session import get_db_session
from stock_platform.trading.controlled_live_order_smoke_service import (
    ControlledLiveOrderSmokeError,
    ControlledLiveOrderSmokeService,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    MAX_SMOKE_AMOUNT,
    confirmation_text_for_side,
)

router = APIRouter(
    prefix="/api/v1/user/accounts",
    tags=["User Controlled Live Order Smoke"],
)


class LiveOrderPreviewBody(BaseModel):
    market: str = Field(min_length=3, max_length=30)
    side: str = Field(min_length=3, max_length=4)
    amount: Decimal | None = Field(default=None, gt=0)
    limit_price: Decimal | None = Field(default=None, gt=0)
    # MARKET | LIMIT — Preview는 업비트 4경로(시장/지정 × 매수/매도) 지원
    order_type: str | None = Field(default="MARKET", max_length=10)
    idempotency_key: str | None = Field(default=None, max_length=128)


class LiveOrderConfirmBody(BaseModel):
    market: str = Field(min_length=3, max_length=30)
    side: str = Field(min_length=3, max_length=4)
    amount: Decimal = Field(gt=0, le=MAX_SMOKE_AMOUNT)
    limit_price: Decimal = Field(gt=0)
    confirmation_text: str = Field(min_length=8, max_length=64)
    arm_token: str | None = None
    execute_live: bool = False
    idempotency_key: str | None = Field(default=None, max_length=128)
    preview_id: str | None = None
    order_test_fingerprint: str | None = Field(default=None, max_length=128)
    order_test_tested_at: str | None = None
    smoke_buy_run_id: str | None = None


class LiveOrderTestBody(BaseModel):
    market: str = Field(min_length=3, max_length=30)
    side: str = Field(min_length=3, max_length=4)
    amount: Decimal | None = Field(default=None, gt=0)
    limit_price: Decimal | None = Field(default=None, gt=0)
    order_type: str | None = Field(default="MARKET", max_length=10)
    identifier: str | None = Field(default=None, max_length=36)
    smoke_buy_run_id: str | None = None
    # 네트워크 스킵은 서버 테스트 전용 — 운영 API에서는 항상 False
    skip_network: bool = False


def _map_error(exc: ControlledLiveOrderSmokeError) -> HTTPException:
    code = str(getattr(exc, "code", None) or exc)
    http_status = int(getattr(exc, "http_status", 0) or 0)
    details = list(getattr(exc, "details", []) or [])
    message = str(getattr(exc, "message", None) or code)

    if code in {"FORBIDDEN", "UBA_NOT_FOUND"}:
        status_code = (
            status.HTTP_403_FORBIDDEN
            if code == "FORBIDDEN"
            else status.HTTP_404_NOT_FOUND
        )
    elif code in {"LIVE_SMOKE_DB_ERROR", "LIVE_SMOKE_NOT_QUEUED", "LIVE_SMOKE_INTERNAL_ERROR"}:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    elif http_status in {409, 422, 500, 503}:
        status_code = http_status
    elif code.startswith("RISK_") or code == "RISK_ENGINE_BLOCKED":
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_400_BAD_REQUEST

    # 구조화 detail (FE / Axios) — Secret/Traceback 미포함
    if (
        details
        or code.startswith("RISK_")
        or code.startswith("LIVE_SMOKE_")
        or http_status in {409, 500, 503}
    ):
        detail: dict[str, object] = {
            "error_code": code,
            "code": code,
            "message": message,
            "details": details,
            "order_submitted": bool(
                getattr(exc, "order_submitted", False)
            ),
            "create_order_calls": int(
                getattr(exc, "create_order_calls", 0) or 0
            ),
            "broker_order_id": None,
            "status": getattr(exc, "status_code", None)
            or (
                "FAILED"
                if code.startswith("LIVE_SMOKE_")
                else "REJECTED"
            ),
            "broker_order_status": "NOT_SUBMITTED",
            "run_id": getattr(exc, "run_id", None),
            "retry_forbidden": code.startswith("LIVE_SMOKE_"),
        }
        return HTTPException(status_code=status_code, detail=detail)

    return HTTPException(status_code=status_code, detail=code)


@router.get("/live-order-smoke/meta")
def user_live_order_smoke_meta():
    return {
        "confirmation_buy": confirmation_text_for_side("BUY"),
        "confirmation_sell": confirmation_text_for_side("SELL"),
        "max_amount": str(MAX_SMOKE_AMOUNT),
        "order_type_preview": ["MARKET", "LIMIT"],
        "order_type_confirm": "LIMIT_ONLY",
        "repeat_orders": False,
    }


@router.get("/{uba_id}/live-order-preflight")
def user_live_order_preflight(
    uba_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        result = ControlledLiveOrderSmokeService(session).preflight(
            uba_id=int(uba_id),
            user_id=int(user.user_id),
            actor=user.username,
        )
        session.commit()
        return result
    except ControlledLiveOrderSmokeError as exc:
        session.rollback()
        raise _map_error(exc) from exc


@router.post("/{uba_id}/live-order-preview")
def user_live_order_preview(
    uba_id: int,
    body: LiveOrderPreviewBody,
    user: AuthenticatedUser = Depends(require_permission("trading:write")),
    session: Session = Depends(get_db_session),
):
    try:
        result = ControlledLiveOrderSmokeService(session).preview(
            uba_id=int(uba_id),
            user_id=int(user.user_id),
            actor=user.username,
            market=body.market,
            side=body.side,
            amount=body.amount,
            limit_price=body.limit_price,
            order_type=body.order_type,
            idempotency_key=body.idempotency_key,
        )
        session.commit()
        return result
    except ControlledLiveOrderSmokeError as exc:
        session.rollback()
        raise _map_error(exc) from exc


@router.post("/{uba_id}/live-order-test")
def user_live_order_test(
    uba_id: int,
    body: LiveOrderTestBody,
    user: AuthenticatedUser = Depends(require_permission("trading:write")),
    session: Session = Depends(get_db_session),
):
    """공식 주문 생성 테스트 (POST /v1/orders/test). 실주문 아님."""

    try:
        result = ControlledLiveOrderSmokeService(session).order_test(
            uba_id=int(uba_id),
            user_id=int(user.user_id),
            actor=user.username,
            market=body.market,
            side=body.side,
            amount=body.amount,
            limit_price=body.limit_price,
            order_type=body.order_type,
            identifier=body.identifier,
            # 운영 경로: 네트워크 스킵 강제 금지
            skip_network=False,
            smoke_buy_run_id=body.smoke_buy_run_id,
        )
        session.commit()
        return result
    except ControlledLiveOrderSmokeError as exc:
        session.rollback()
        raise _map_error(exc) from exc


@router.post("/{uba_id}/live-order-confirm")
def user_live_order_confirm(
    uba_id: int,
    body: LiveOrderConfirmBody,
    user: AuthenticatedUser = Depends(require_permission("trading:write")),
    session: Session = Depends(get_db_session),
):
    try:
        result = ControlledLiveOrderSmokeService(session).confirm(
            uba_id=int(uba_id),
            user_id=int(user.user_id),
            actor=user.username,
            market=body.market,
            side=body.side,
            amount=body.amount,
            limit_price=body.limit_price,
            confirmation_text=body.confirmation_text,
            arm_token=body.arm_token,
            execute_live=bool(body.execute_live),
            idempotency_key=body.idempotency_key,
            preview_id=body.preview_id,
            order_test_fingerprint=body.order_test_fingerprint,
            order_test_tested_at=body.order_test_tested_at,
            smoke_buy_run_id=body.smoke_buy_run_id,
        )
        session.commit()
        return result
    except ControlledLiveOrderSmokeError as exc:
        session.rollback()
        raise _map_error(exc) from exc


@router.get("/{uba_id}/live-order-smoke/{run_id}")
def user_live_order_smoke_run(
    uba_id: int,
    run_id: str,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return ControlledLiveOrderSmokeService(session).get_run(
            uba_id=int(uba_id),
            user_id=int(user.user_id),
            run_id=run_id,
        )
    except ControlledLiveOrderSmokeError as exc:
        raise _map_error(exc) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
