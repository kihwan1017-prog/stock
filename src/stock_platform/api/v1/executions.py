from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import (
    get_db_session,
)
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
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(
        get_db_session
    ),
):
    stmt = (
        select(TradingExecution)
        .order_by(
            TradingExecution.executed_at.desc()
        )
        .limit(limit)
    )
    return list(session.scalars(stmt))


@router.get(
    "/orders/{order_id}/executions"
)
def list_order_executions(
    order_id: int,
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(
        get_db_session
    ),
):
    return TradingExecutionRepository(
        session
    ).list_by_order_id(order_id)
