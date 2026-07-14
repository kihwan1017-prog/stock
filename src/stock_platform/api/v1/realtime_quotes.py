from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from stock_platform.realtime.manager import (
    realtime_manager,
)


router = APIRouter(
    prefix="/api/v1/realtime-quotes",
    tags=["Realtime Quotes"],
)


class StartUpbitRequest(BaseModel):
    symbols: list[str] = Field(
        min_length=1,
        max_length=200,
    )


@router.post("/upbit/start")
async def start_upbit_realtime(
    request: StartUpbitRequest,
):
    try:
        return await realtime_manager.start_upbit(
            symbols=request.symbols
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{client_id}/stop")
async def stop_realtime_client(client_id: str):
    await realtime_manager.stop(client_id)
    return {
        "client_id": client_id.upper(),
        "stopped": True,
    }


@router.get("/status")
async def get_realtime_status():
    return await realtime_manager.status()


@router.get("/{exchange_code}/{symbol}")
async def get_latest_quote(
    exchange_code: str,
    symbol: str,
):
    quote = await realtime_manager.cache.get(
        exchange_code=exchange_code,
        symbol=symbol,
    )

    if quote is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Realtime quote not found",
        )

    return quote


@router.get("")
async def list_latest_quotes():
    return await realtime_manager.cache.list_all()


@router.get("/stream/sse")
async def stream_realtime_quotes():
    async def event_generator():
        async for quote in realtime_manager.bus.subscribe():
            payload = json.dumps(
                {
                    "exchange_code": quote.exchange_code,
                    "symbol": quote.symbol,
                    "event_type": quote.event_type.value,
                    "trade_price": str(quote.trade_price),
                    "change_rate": (
                        str(quote.change_rate)
                        if quote.change_rate is not None
                        else None
                    ),
                    "event_time": quote.event_time.isoformat(),
                    "received_at": (
                        quote.received_at.isoformat()
                    ),
                },
                ensure_ascii=False,
            )
            yield f"data: {payload}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
