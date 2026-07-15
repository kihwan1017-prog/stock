from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskOrderRequest,
    RiskOrderSide,
)
from stock_platform.risk_engine.runtime import (
    realtime_risk_engine,
    realtime_risk_policy,
)


router = APIRouter(
    prefix="/api/v1/realtime-risk",
    tags=["Realtime Risk Engine"],
)


class RiskCheckRequest(BaseModel):
    exchange_code: str = Field(
        min_length=1,
        max_length=20,
    )
    symbol: str = Field(
        min_length=1,
        max_length=30,
    )
    side: RiskOrderSide
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    account_id: int = Field(gt=0)
    requested_at: datetime

    cash_balance: Decimal = Field(ge=0)
    total_asset_value: Decimal = Field(gt=0)
    invested_amount: Decimal = Field(ge=0)
    daily_realized_profit_loss: Decimal
    daily_unrealized_profit_loss: Decimal
    open_position_count: int = Field(ge=0)
    symbol_position_quantity: Decimal = Field(
        default=Decimal("0"),
        ge=0,
    )


@router.post("/check")
def check_realtime_risk(
    request: RiskCheckRequest,
):
    try:
        return realtime_risk_engine.evaluate(
            order=RiskOrderRequest(
                exchange_code=request.exchange_code,
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                price=request.price,
                account_id=request.account_id,
                requested_at=request.requested_at,
            ),
            account=RiskAccountState(
                cash_balance=request.cash_balance,
                total_asset_value=(
                    request.total_asset_value
                ),
                invested_amount=request.invested_amount,
                daily_realized_profit_loss=(
                    request.daily_realized_profit_loss
                ),
                daily_unrealized_profit_loss=(
                    request.daily_unrealized_profit_loss
                ),
                open_position_count=(
                    request.open_position_count
                ),
                symbol_position_quantity=(
                    request.symbol_position_quantity
                ),
            ),
            policy=realtime_risk_policy,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/status")
def get_realtime_risk_status():
    return {
        "max_order_amount": str(
            realtime_risk_policy.max_order_amount
        ),
        "max_order_quantity": str(
            realtime_risk_policy.max_order_quantity
        ),
        "max_open_positions": (
            realtime_risk_policy.max_open_positions
        ),
        "max_investment_ratio": str(
            realtime_risk_policy.max_investment_ratio
        ),
        "max_daily_loss": str(
            realtime_risk_policy.max_daily_loss
        ),
        "trading_start_time": (
            realtime_risk_policy
            .trading_start_time.isoformat()
        ),
        "trading_end_time": (
            realtime_risk_policy
            .trading_end_time.isoformat()
        ),
        "emergency_stop_enabled": (
            realtime_risk_policy
            .emergency_stop_enabled
        ),
    }
