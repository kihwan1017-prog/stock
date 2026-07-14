from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stock_platform.risk.engine import (
    RiskManagementEngine,
    RiskValidationError,
)
from stock_platform.risk.models import (
    ExitEvaluationRequest,
    PositionSizingMode,
    PositionSizingRequest,
    RiskPolicy,
)


router = APIRouter(
    prefix="/api/v1/risk",
    tags=["Risk"],
)


class RiskPolicyRequest(BaseModel):
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
    maximum_positions: int = Field(
        default=5,
        ge=1,
    )
    minimum_order_amount: Decimal = Field(
        default=Decimal("10000"),
        ge=0,
    )


class PositionPlanRequest(BaseModel):
    portfolio_value: Decimal = Field(gt=0)
    available_cash: Decimal = Field(ge=0)
    current_price: Decimal = Field(gt=0)
    current_position_count: int = Field(ge=0)
    policy: RiskPolicyRequest


class ExitRequest(BaseModel):
    entry_price: Decimal = Field(gt=0)
    current_price: Decimal = Field(gt=0)
    highest_price: Decimal = Field(gt=0)
    stop_loss_price: Decimal = Field(gt=0)
    take_profit_price: Decimal = Field(gt=0)
    trailing_stop_ratio: Decimal | None = Field(
        default=None,
        gt=0,
        le=1,
    )


@router.post("/position-plan")
def create_position_plan(request: PositionPlanRequest):
    engine = RiskManagementEngine()
    policy = RiskPolicy(**request.policy.model_dump())

    try:
        return engine.create_position_plan(
            PositionSizingRequest(
                portfolio_value=request.portfolio_value,
                available_cash=request.available_cash,
                current_price=request.current_price,
                current_position_count=(
                    request.current_position_count
                ),
                policy=policy,
            )
        )
    except RiskValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/exit-decision")
def evaluate_exit(request: ExitRequest):
    engine = RiskManagementEngine()

    try:
        return engine.evaluate_exit(
            ExitEvaluationRequest(
                entry_price=request.entry_price,
                current_price=request.current_price,
                highest_price=request.highest_price,
                stop_loss_price=request.stop_loss_price,
                take_profit_price=request.take_profit_price,
                trailing_stop_ratio=(
                    request.trailing_stop_ratio
                ),
            )
        )
    except RiskValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
