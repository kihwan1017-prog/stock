"""Deprecated STEP32 compatibility API.

Prefer:
- GET /paper-accounts/{id}/positions
- GET /dashboard/admin-summary
- POST /risk (RiskManagementEngine) / risk_engine guards

In-memory Position/Portfolio 스택은 제거했다.
GET은 Paper DB를 조회하고, risk/check는 InMemoryRiskGate를 유지한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.order.models import OrderSide
from stock_platform.risk.legacy_gate import InMemoryRiskGate
from stock_platform.risk.models import RiskLimits, RiskRequest
from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
)
from stock_platform.trading.account_service import (
    PaperAccountService,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["step32-deprecated"],
)

_legacy_risk = InMemoryRiskGate(
    RiskLimits(
        Decimal("1000000"),
        Decimal("5000000"),
        Decimal("300000"),
        5,
    )
)

ZERO = Decimal("0")


class ExecutionRequest(BaseModel):
    account_id: str
    market: str = "KRX"
    symbol: str
    side: str
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    execution_id: str


class RiskCheckRequest(BaseModel):
    order_amount: Decimal
    current_position_amount: Decimal
    daily_realized_pnl: Decimal
    open_positions: int
    creates_new_position: bool


@router.post(
    "/positions/executions",
    deprecated=True,
    summary="[DEPRECATED] Paper apply_fill 호환",
)
def apply_execution(
    request: ExecutionRequest,
    session: Session = Depends(get_db_session),
):
    account_id = int(request.account_id)
    side = OrderSide(request.side.upper())
    trade = PaperAccountService(session).apply_fill(
        account_id=account_id,
        exchange_code=request.market,
        symbol=request.symbol,
        side=side,
        quantity=request.quantity,
        fill_price=request.price,
    )
    return {
        "deprecated": True,
        "prefer": "POST /paper-orders or order-execution",
        "account_id": account_id,
        "symbol": trade.symbol,
        "quantity": str(trade.quantity),
        "fill_price": str(trade.fill_price),
        "execution_id": request.execution_id,
    }


@router.get(
    "/positions",
    deprecated=True,
    summary="[DEPRECATED] Paper 포지션 목록",
)
def list_positions(
    account_id: str | None = None,
    session: Session = Depends(get_db_session),
):
    stmt = select(PaperPosition).where(
        PaperPosition.quantity > ZERO
    )
    if account_id is not None:
        stmt = stmt.where(
            PaperPosition.account_id == int(account_id)
        )
    rows = list(session.scalars(stmt))
    return {
        "deprecated": True,
        "prefer": "/paper-accounts/{id}/positions",
        "items": [
            {
                "account_id": str(row.account_id),
                "market": row.exchange_code,
                "symbol": row.symbol,
                "quantity": str(row.quantity),
                "average_price": str(
                    row.average_entry_price
                ),
                "average_entry_price": str(
                    row.average_entry_price
                ),
                "realized_pnl": str(
                    row.realized_profit_loss
                ),
            }
            for row in rows
        ],
    }


@router.get(
    "/portfolio/summary",
    deprecated=True,
    summary="[DEPRECATED] Paper 포트폴리오 요약",
)
def portfolio_summary(
    account_id: str = Query(...),
    session: Session = Depends(get_db_session),
):
    account = session.get(PaperAccount, int(account_id))
    if account is None:
        return {
            "deprecated": True,
            "prefer": "/dashboard/admin-summary",
            "account_id": account_id,
            "position_count": 0,
            "total_market_value": "0",
            "total_realized_pnl": "0",
            "total_unrealized_pnl": "0",
        }
    positions = list(
        session.scalars(
            select(PaperPosition).where(
                PaperPosition.account_id == account.account_id,
                PaperPosition.quantity > ZERO,
            )
        )
    )
    market_value = sum(
        (
            row.quantity * row.average_entry_price
            for row in positions
        ),
        ZERO,
    )
    return {
        "deprecated": True,
        "prefer": "/dashboard/admin-summary",
        "account_id": account_id,
        "position_count": len(positions),
        "total_market_value": str(market_value),
        "total_realized_pnl": str(
            account.realized_profit_loss
        ),
        "total_unrealized_pnl": "0",
        "available_cash": str(account.available_cash),
    }


@router.post(
    "/risk/check",
    deprecated=True,
    summary="[DEPRECATED] 인메모리 한도 검사",
)
def risk_check(request: RiskCheckRequest):
    decision = _legacy_risk.evaluate(
        RiskRequest(**request.model_dump())
    )
    return {
        "deprecated": True,
        "prefer": "/api/v1/risk or risk_engine",
        "allowed": decision.allowed,
        "reasons": list(decision.reasons),
    }


@router.get(
    "/dashboard/summary",
    deprecated=True,
    summary="[DEPRECATED] Paper 기반 요약",
)
def dashboard_summary(
    account_id: str = Query(...),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    summary = portfolio_summary(
        account_id=account_id,
        session=session,
    )
    positions = list_positions(
        account_id=account_id,
        session=session,
    )
    return {
        "deprecated": True,
        "prefer": "/dashboard/admin-summary",
        "portfolio": summary,
        "positions": positions.get("items", []),
        "risk": {
            "kill_switch_enabled": (
                _legacy_risk.kill_switch_enabled
            )
        },
    }
