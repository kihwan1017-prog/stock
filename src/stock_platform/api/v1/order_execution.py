from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.account_ownership import (
    assert_active_broker_account_for_trading,
    assert_paper_account_access,
    require_live_broker_account_id,
)
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.database.session import get_db_session
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import (
    OrderSide,
    OrderTimeInForce,
    OrderType,
)


router = APIRouter(
    prefix="/api/v1/order-execution",
    tags=["Order Execution"],
)


class SubmitOrderRequest(BaseModel):
    account_id: int = Field(gt=0)
    # STEP8-1 — LIVE 키움·업비트 필수
    user_broker_account_id: int | None = Field(default=None, gt=0)
    broker_code: str = "KIWOOM"
    exchange_code: str
    # PAPER(기본) | LIVE
    environment: str = "PAPER"
    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.LIMIT
    quantity: Decimal | None = Field(default=None, gt=0)
    order_amount: Decimal | None = Field(default=None, gt=0)
    price: Decimal | None = None
    time_in_force: OrderTimeInForce = OrderTimeInForce.DAY
    strategy_code: str | None = None
    strategy_deployment_id: int | None = None
    portfolio_id: int | None = None
    position_id: int | None = None
    client_order_id: str | None = None
    idempotency_key: str | None = None
    account_number: str | None = None
    portfolio_value: Decimal | None = None
    available_cash: Decimal | None = None
    current_position_count: int = 0
    metadata_payload: dict[str, Any] = Field(default_factory=dict)
    actor: str = "API"


@router.post("/submit")
def submit_order(
    request: SubmitOrderRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    """Admin/API 주문 단일 진입점 — Risk + Kill Switch 필수 (우회 불가)."""

    enforce_rate_limit(
        http_request,
        scope="order_execution_submit",
        limit=60,
        window_seconds=60,
    )
    # Paper 원장 계좌 소유권 (기존 account_id)
    assert_paper_account_access(
        user, request.account_id, session
    )

    environment = (request.environment or "PAPER").upper()
    broker_code = (request.broker_code or "KIWOOM").upper()
    require_live_broker_account_id(
        environment=environment,
        broker_code=broker_code,
        user_broker_account_id=request.user_broker_account_id,
    )

    uba = None
    external_account_ref = None
    owner_user_id = int(user.user_id)
    if request.user_broker_account_id is not None:
        uba = assert_active_broker_account_for_trading(
            user,
            int(request.user_broker_account_id),
            session,
            expected_broker_code=broker_code,
        )
        external_account_ref = uba.masked_account_number
        owner_user_id = int(uba.user_id)

    if request.quantity is None and request.order_amount is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="quantity or order_amount is required",
        )

    try:
        result = OrderExecutionService(session).submit(
            OrderExecutionCommand(
                account_id=request.account_id,
                user_broker_account_id=(
                    None
                    if uba is None
                    else int(uba.user_broker_account_id)
                ),
                broker_code=broker_code,
                exchange_code=request.exchange_code,
                environment=environment,
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                order_amount=request.order_amount,
                price=request.price,
                time_in_force=request.time_in_force,
                strategy_code=request.strategy_code,
                strategy_deployment_id=(
                    request.strategy_deployment_id
                ),
                portfolio_id=request.portfolio_id,
                position_id=request.position_id,
                client_order_id=request.client_order_id,
                idempotency_key=request.idempotency_key,
                account_number=request.account_number,
                external_account_ref=external_account_ref,
                owner_user_id=owner_user_id,
                user_id=int(user.user_id),
                order_source="MANUAL",
                is_risk_reducing=(
                    request.side.value.upper() == "SELL"
                ),
                portfolio_value=request.portfolio_value,
                available_cash=request.available_cash,
                current_position_count=(
                    request.current_position_count
                ),
                # 공개 API에서는 항상 Risk/Kill Switch 강제
                skip_risk_checks=False,
                metadata_payload=request.metadata_payload,
                actor=request.actor or user.username,
            )
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    status_code = (
        status.HTTP_202_ACCEPTED
        if result.allowed
        else status.HTTP_409_CONFLICT
    )
    return {
        "allowed": result.allowed,
        "reason_code": result.reason_code,
        "order_id": result.order_id,
        "outbox_id": result.outbox_id,
        "status_code": result.status_code,
        "client_order_id": result.client_order_id,
        "quantity": result.quantity,
        "price": result.price,
        "position_plan": result.position_plan,
        "user_broker_account_id": (
            None if uba is None else int(uba.user_broker_account_id)
        ),
        "http_status": status_code,
    }
