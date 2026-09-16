from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.account_ownership import (
    assert_paper_account_access,
)
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session
from stock_platform.order.trading_guards import (
    TradingGuardError,
    require_order_safety,
)
from stock_platform.trading.models import (
    OrderSide,
    OrderType,
)
from stock_platform.trading.paper_engine import (
    PaperOrderValidationError,
)
from stock_platform.trading.repository import (
    PaperOrderRepository,
)
from stock_platform.trading.service import (
    PaperOrderService,
)


router = APIRouter(
    prefix="/api/v1/paper-orders",
    tags=["Paper Orders"],
)


class CreatePaperOrderRequest(BaseModel):
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    side: OrderSide
    order_type: OrderType
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = Field(default=None, gt=0)
    position_plan_id: int | None = Field(
        default=None,
        gt=0,
    )
    auto_accept: bool = True
    # STEP52: 호출자가 소유한 Paper account_id 필수
    account_id: int = Field(gt=0)
    account_number: str | None = None
    broker_code: str = "KIWOOM"


class FillPaperOrderRequest(BaseModel):
    fill_quantity: Decimal = Field(gt=0)
    fill_price: Decimal = Field(gt=0)


class RejectPaperOrderRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _service(session: Session) -> PaperOrderService:
    return PaperOrderService(
        PaperOrderRepository(session)
    )


def _resolve_price(request: CreatePaperOrderRequest) -> Decimal:
    if request.price is not None and request.price > 0:
        return request.price
    # MARKET 등 가격 없을 때 Risk용 참조가 — 거부
    raise TradingGuardError(
        "price is required for Risk + Kill Switch checks"
    )


@router.post("")
def create_paper_order(
    request: CreatePaperOrderRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    """Paper 주문 — Kill Switch + Risk 통과 후에만 생성."""

    enforce_rate_limit(
        http_request,
        scope="paper_order_create",
        limit=60,
        window_seconds=60,
    )
    assert_paper_account_access(
        user, request.account_id, session
    )

    try:
        account_number = (
            (request.account_number or "").strip()
            or get_settings().kiwoom_account_number.strip()
            or f"PAPER-{request.account_id}"
        )
        require_order_safety(
            session,
            side=request.side.value,
            account_number=account_number,
            account_id=request.account_id,
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            quantity=request.quantity,
            price=_resolve_price(request),
            broker_code=request.broker_code,
            user_id=int(user.user_id),
            order_source="MANUAL",
            is_risk_reducing=(
                request.side.value.upper() == "SELL"
            ),
            environment="PAPER",
        )
        return _service(session).create(
            account_id=request.account_id,
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            position_plan_id=request.position_plan_id,
            auto_accept=request.auto_accept,
        )
    except TradingGuardError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except PaperOrderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{order_id}/fills")
def fill_paper_order(
    order_id: int,
    request: FillPaperOrderRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        order = PaperOrderRepository(session).get(order_id)
        if order is None:
            raise LookupError(f"Paper order not found: {order_id}")
        assert_paper_account_access(
            user, int(order.account_id), session
        )
        return _service(session).fill(
            order_id=order_id,
            fill_quantity=request.fill_quantity,
            fill_price=request.fill_price,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperOrderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{order_id}/cancel")
def cancel_paper_order(
    order_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    # 취소는 리스크 축소이므로 Kill Switch와 무관하게 허용
    try:
        order = PaperOrderRepository(session).get(order_id)
        if order is None:
            raise LookupError(f"Paper order not found: {order_id}")
        assert_paper_account_access(
            user, int(order.account_id), session
        )
        return _service(session).cancel(
            order_id=order_id
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperOrderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{order_id}/reject")
def reject_paper_order(
    order_id: int,
    request: RejectPaperOrderRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        order = PaperOrderRepository(session).get(order_id)
        if order is None:
            raise LookupError(f"Paper order not found: {order_id}")
        assert_paper_account_access(
            user, int(order.account_id), session
        )
        return _service(session).reject(
            order_id=order_id,
            reason=request.reason,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperOrderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("")
def list_paper_orders(
    account_id: int | None = None,
    exchange_code: str | None = None,
    limit: int = 100,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """
    Paper 주문 목록.
    비관리자는 account_id 필수 + 소유권 검사 후 해당 계좌 주문만 반환.
    """

    if not user.is_admin:
        if account_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="account_id 가 필요합니다.",
            )
        assert_paper_account_access(user, account_id, session)

    rows = PaperOrderRepository(session).list_recent(
        account_id=account_id,
        exchange_code=exchange_code,
        limit=limit,
    )
    return rows
