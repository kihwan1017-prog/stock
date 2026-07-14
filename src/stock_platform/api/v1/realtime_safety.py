from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from stock_platform.realtime.runtime import (
    realtime_safety_guard,
)


router = APIRouter(
    prefix="/api/v1/realtime-safety",
    tags=["Realtime Safety"],
)


class RealizedProfitLossRequest(BaseModel):
    realized_profit_loss: Decimal


@router.get("/status")
def get_realtime_safety_status():
    return {
        "daily_realized_loss": str(
            realtime_safety_guard.daily_realized_loss
        ),
    }


@router.post("/realized-profit-loss")
def add_realized_profit_loss(
    request: RealizedProfitLossRequest,
):
    realtime_safety_guard.add_realized_profit_loss(
        request.realized_profit_loss
    )

    return {
        "daily_realized_loss": str(
            realtime_safety_guard.daily_realized_loss
        ),
    }


@router.post("/reset-daily")
def reset_daily_safety_counters():
    realtime_safety_guard.reset_daily_counters()
    return {
        "reset": True,
        "daily_realized_loss": "0",
    }
