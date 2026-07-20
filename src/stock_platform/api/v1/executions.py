from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.auth.account_ownership import (
    assert_trading_account_access,
)
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import (
    get_db_session,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.trading.execution_entities import (
    TradingExecution,
)
from stock_platform.trading.execution_repository import (
    TradingExecutionRepository,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Executions"],
)


@router.get("/executions")
def list_executions(
    account_id: int | None = Query(
        default=None,
        description="비관리자는 필수 — 본인 계좌 체결만 조회",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(
        get_db_session
    ),
):
    if not user.is_admin:
        if account_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="account_id 가 필요합니다.",
            )
        assert_trading_account_access(user, account_id, session)
    elif account_id is not None:
        assert_trading_account_access(user, account_id, session)

    stmt = select(TradingExecution).order_by(
        TradingExecution.executed_at.desc()
    )
    if account_id is not None:
        stmt = stmt.join(
            TradingOrderEntity,
            TradingExecution.order_id == TradingOrderEntity.order_id,
        ).where(TradingOrderEntity.account_id == account_id)
    stmt = stmt.limit(limit)
    return list(session.scalars(stmt).unique())


@router.get(
    "/orders/{order_id}/executions"
)
def list_order_executions(
    order_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(
        get_db_session
    ),
):
    order = TradingOrderRepository(session).get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order not found: {order_id}",
        )
    assert_trading_account_access(
        user, int(order.account_id), session
    )
    return TradingExecutionRepository(
        session
    ).list_by_order_id(order_id)
