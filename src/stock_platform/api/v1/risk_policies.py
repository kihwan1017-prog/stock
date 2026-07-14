from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.risk.models import PositionSizingMode
from stock_platform.risk.repository import RiskRepository
from stock_platform.risk.service import RiskService


router = APIRouter(
    prefix="/api/v1/risk-policies",
    tags=["Risk Policies"],
)


class RiskPolicyCreateRequest(BaseModel):
    policy_name: str = Field(min_length=1, max_length=100)
    position_sizing_mode: PositionSizingMode
    fixed_amount: Decimal | None = None
    portfolio_ratio: Decimal | None = None
    risk_per_trade_ratio: Decimal = Field(
        default=Decimal("0.01"),
        gt=0,
        le=1,
    )
    stop_loss_ratio: Decimal = Field(
        default=Decimal("0.03"),
        gt=0,
        le=1,
    )
    take_profit_ratio: Decimal = Field(
        default=Decimal("0.06"),
        gt=0,
        le=1,
    )
    trailing_stop_ratio: Decimal | None = Field(
        default=Decimal("0.03"),
        gt=0,
        le=1,
    )
    maximum_position_ratio: Decimal = Field(
        default=Decimal("0.20"),
        gt=0,
        le=1,
    )
    maximum_positions: int = Field(default=5, ge=1)
    minimum_order_amount: Decimal = Field(
        default=Decimal("10000"),
        ge=0,
    )


class PositionPlanCreateRequest(BaseModel):
    policy_id: int = Field(gt=0)
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    portfolio_value: Decimal = Field(gt=0)
    available_cash: Decimal = Field(ge=0)
    current_price: Decimal = Field(gt=0)
    current_position_count: int = Field(ge=0)


@router.post("")
def create_risk_policy(
    request: RiskPolicyCreateRequest,
    session: Session = Depends(get_db_session),
):
    service = RiskService(RiskRepository(session))

    entity = service.create_policy(
        policy_name=request.policy_name,
        position_sizing_mode=request.position_sizing_mode,
        fixed_amount=request.fixed_amount,
        portfolio_ratio=request.portfolio_ratio,
        risk_per_trade_ratio=request.risk_per_trade_ratio,
        stop_loss_ratio=request.stop_loss_ratio,
        take_profit_ratio=request.take_profit_ratio,
        trailing_stop_ratio=request.trailing_stop_ratio,
        maximum_position_ratio=request.maximum_position_ratio,
        maximum_positions=request.maximum_positions,
        minimum_order_amount=request.minimum_order_amount,
    )

    return {
        "policy_id": entity.policy_id,
        "policy_name": entity.policy_name,
        "position_sizing_mode": entity.position_sizing_mode,
        "is_active": entity.is_active,
    }


@router.get("")
def list_risk_policies(
    session: Session = Depends(get_db_session),
):
    rows = RiskRepository(session).list_active_policies()

    return [
        {
            "policy_id": row.policy_id,
            "policy_name": row.policy_name,
            "position_sizing_mode": row.position_sizing_mode,
            "risk_per_trade_ratio": row.risk_per_trade_ratio,
            "stop_loss_ratio": row.stop_loss_ratio,
            "take_profit_ratio": row.take_profit_ratio,
            "maximum_position_ratio": row.maximum_position_ratio,
            "maximum_positions": row.maximum_positions,
            "is_active": row.is_active,
        }
        for row in rows
    ]


@router.post("/position-plans")
def create_position_plan(
    request: PositionPlanCreateRequest,
    session: Session = Depends(get_db_session),
):
    service = RiskService(RiskRepository(session))

    try:
        entity = service.create_and_save_position_plan(
            policy_id=request.policy_id,
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            portfolio_value=request.portfolio_value,
            available_cash=request.available_cash,
            current_price=request.current_price,
            current_position_count=request.current_position_count,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return {
        "position_plan_id": entity.position_plan_id,
        "policy_id": entity.policy_id,
        "exchange_code": entity.exchange_code,
        "symbol": entity.symbol,
        "approved": entity.approved,
        "reason_code": entity.reason_code,
        "quantity": entity.quantity,
        "order_amount": entity.order_amount,
        "entry_price": entity.entry_price,
        "stop_loss_price": entity.stop_loss_price,
        "take_profit_price": entity.take_profit_price,
        "trailing_stop_ratio": entity.trailing_stop_ratio,
        "maximum_loss_amount": entity.maximum_loss_amount,
    }
