from __future__ import annotations

import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from stock_platform.api.deps_admin import require_admin
from stock_platform.realtime.runtime import (
    realtime_signal_bus,
    realtime_strategy_runner,
)


router = APIRouter(
    prefix="/api/v1/realtime-strategy",
    tags=["Realtime Strategy"],
    dependencies=[Depends(require_admin)],
)


class PositionStateRequest(BaseModel):
    exchange_code: str = Field(
        min_length=1,
        max_length=20,
    )
    symbol: str = Field(
        min_length=1,
        max_length=30,
    )
    quantity: Decimal = Field(ge=0)
    average_entry_price: Decimal | None = Field(
        default=None,
        gt=0,
    )


@router.post("/start")
async def start_realtime_strategy():
    try:
        return await realtime_strategy_runner.start()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/stop")
async def stop_realtime_strategy():
    await realtime_strategy_runner.stop()
    return {"stopped": True}


@router.get("/status")
def get_realtime_strategy_status():
    return realtime_strategy_runner.status()


@router.put("/positions")
def set_realtime_position(
    request: PositionStateRequest,
):
    try:
        return realtime_strategy_runner.set_position(
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            quantity=request.quantity,
            average_entry_price=(
                request.average_entry_price
            ),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/positions/{exchange_code}/{symbol}"
)
def get_realtime_position(
    exchange_code: str,
    symbol: str,
):
    return realtime_strategy_runner.get_position(
        exchange_code=exchange_code,
        symbol=symbol,
    )


@router.get("/signals/sse")
async def stream_realtime_signals():
    async def event_generator():
        async for signal in (
            realtime_signal_bus.subscribe()
        ):
            payload = json.dumps(
                {
                    "exchange_code": (
                        signal.exchange_code
                    ),
                    "symbol": signal.symbol,
                    "action": signal.action.value,
                    "signal_price": str(
                        signal.signal_price
                    ),
                    "short_average": (
                        str(signal.short_average)
                        if signal.short_average
                        is not None
                        else None
                    ),
                    "long_average": (
                        str(signal.long_average)
                        if signal.long_average
                        is not None
                        else None
                    ),
                    "change_rate": (
                        str(signal.change_rate)
                        if signal.change_rate
                        is not None
                        else None
                    ),
                    "reason_code": (
                        signal.reason_code
                    ),
                    "generated_at": (
                        signal.generated_at.isoformat()
                    ),
                },
                ensure_ascii=False,
            )
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
