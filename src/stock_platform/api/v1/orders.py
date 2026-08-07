from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.auth.account_ownership import (
    assert_broker_account_access,
    assert_order_resource_access,
    assert_trading_account_access,
)
from stock_platform.database.session import get_db_session
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderSide, OrderTimeInForce, OrderType
from stock_platform.order.repository import TradingOrderRepository

router = APIRouter(prefix="/api/v1/orders", tags=["Orders"])


def _safe_order_dict(order: TradingOrderEntity) -> dict[str, Any]:
    """사용자 응답 전용 직렬화.

    STEP 8-5-14 — resolver_claimed_by/at/expires/run_token 같은 Scheduler
    내부 Claim 필드는 절대 노출하지 않는다. 대신 원격 재조회 진행 상황을
    사용자가 이해할 수 있는 안전한 필드로만 제공한다.
    """

    return {
        "order_id": int(order.order_id),
        "client_order_id": order.client_order_id,
        "broker_order_id": order.broker_order_id,
        "account_id": order.account_id,
        "user_broker_account_id": order.user_broker_account_id,
        "broker_code": order.broker_code,
        "exchange_code": order.exchange_code,
        "symbol": order.symbol,
        "strategy_code": order.strategy_code,
        "side_code": order.side_code,
        "order_type_code": order.order_type_code,
        "time_in_force_code": order.time_in_force_code,
        "order_quantity": order.order_quantity,
        "order_price": order.order_price,
        "filled_quantity": order.filled_quantity,
        "remaining_quantity": order.remaining_quantity,
        "filled_amount": order.filled_amount,
        "average_fill_price": order.average_fill_price,
        "status_code": order.status_code,
        "reject_code": order.reject_code,
        "reject_message": order.reject_message,
        "failure_code": order.failure_code,
        "failure_message": order.failure_message,
        "submission_attempt_count": int(
            getattr(order, "submission_attempt_count", 0) or 0
        ),
        "submission_generation": order.submission_generation,
        "ambiguous_since": (
            order.ambiguous_since.isoformat()
            if order.ambiguous_since
            else None
        ),
        # 안전 필드만 — Claim 토큰/소유자 등 내부 필드는 절대 미노출
        "next_remote_lookup_at": (
            order.next_remote_lookup_at.isoformat()
            if order.next_remote_lookup_at
            else None
        ),
        "last_remote_lookup_at": (
            order.last_remote_lookup_at.isoformat()
            if order.last_remote_lookup_at
            else None
        ),
        "remote_lookup_attempt_count": int(
            order.remote_lookup_attempt_count or 0
        ),
        "manual_review_required": (
            order.status_code == "MANUAL_REVIEW_REQUIRED"
        ),
        "remote_order_found": (
            order.remote_lookup_status == "FOUND_MATCHED"
        ),
        "requested_at": (
            order.requested_at.isoformat() if order.requested_at else None
        ),
        "sent_at": order.sent_at.isoformat() if order.sent_at else None,
        "accepted_at": (
            order.accepted_at.isoformat() if order.accepted_at else None
        ),
        "filled_at": order.filled_at.isoformat() if order.filled_at else None,
        "cancelled_at": (
            order.cancelled_at.isoformat() if order.cancelled_at else None
        ),
        "created_at": (
            order.created_at.isoformat() if order.created_at else None
        ),
        "updated_at": (
            order.updated_at.isoformat() if order.updated_at else None
        ),
    }


class CreateOrderRequest(BaseModel):
    account_id: int = Field(gt=0)
    broker_code: str = Field(min_length=1, max_length=30)
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    side: OrderSide
    order_type: OrderType
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = Field(default=None, gt=0)
    time_in_force: OrderTimeInForce = OrderTimeInForce.DAY
    strategy_code: str | None = Field(default=None, max_length=100)
    strategy_deployment_id: int | None = None
    portfolio_id: int | None = None
    position_id: int | None = None
    client_order_id: str | None = Field(default=None, max_length=100)
    metadata_payload: dict[str, Any] = {}
    actor: str = Field(default="API", max_length=100)


@router.post("", status_code=status.HTTP_400_BAD_REQUEST)
def create_order(
    request: CreateOrderRequest,
    _: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    """가드 없는 직접 생성은 차단 — order-execution/submit 사용."""

    _ = (request, session)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "직접 주문 생성은 비활성입니다. "
            "POST /api/v1/order-execution/submit 를 사용하세요 "
            "(Risk + Kill Switch 필수)."
        ),
    )


@router.get("/{order_id}")
def get_order(
    order_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    entity = TradingOrderRepository(session).get(order_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_order_resource_access(user, entity, session)
    return _safe_order_dict(entity)


@router.get("/{order_id}/history")
def get_order_history(
    order_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    repo = TradingOrderRepository(session)
    entity = repo.get(order_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Order not found")
    assert_order_resource_access(user, entity, session)
    return repo.history(order_id)


@router.get("")
def list_orders(
    account_id: int | None = None,
    user_broker_account_id: int | None = Query(
        default=None,
        description="STEP8-1 — UserBrokerAccount 단위 주문 조회",
    ),
    status_code: str | None = None,
    broker_code: str | None = None,
    exchange_code: str | None = None,
    symbol: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    if not user.is_admin:
        if account_id is None and user_broker_account_id is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "account_id 또는 user_broker_account_id 가 필요합니다."
                ),
            )
        if account_id is not None:
            assert_trading_account_access(user, account_id, session)
        if user_broker_account_id is not None:
            assert_broker_account_access(
                user, user_broker_account_id, session
            )
    else:
        if account_id is not None:
            assert_trading_account_access(user, account_id, session)
        if user_broker_account_id is not None:
            assert_broker_account_access(
                user, user_broker_account_id, session
            )
    rows = TradingOrderRepository(session).list(
        account_id,
        status_code,
        exchange_code,
        symbol,
        limit,
        offset,
        broker_code,
        user_broker_account_id,
    )
    return [_safe_order_dict(r) for r in rows]
