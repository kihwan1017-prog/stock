from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stock_platform.realtime.ai_runner import (
    realtime_ai_review_runner,
)


router = APIRouter(
    prefix="/api/v1/realtime-ai",
    tags=["Realtime AI"],
)


class RealtimeAiReviewApiRequest(BaseModel):
    exchange_code: str = Field(
        min_length=1,
        max_length=20,
    )
    symbol: str = Field(
        min_length=1,
        max_length=30,
    )
    current_price: Decimal = Field(gt=0)
    news_limit: int = Field(default=10, ge=0, le=100)
    disclosure_limit: int = Field(
        default=10,
        ge=0,
        le=100,
    )
    lookback_days: int = Field(
        default=30,
        ge=1,
        le=365,
    )


@router.post("/review")
async def review_realtime_symbol(
    request: RealtimeAiReviewApiRequest,
):
    try:
        return await (
            realtime_ai_review_runner.review_symbol(
                exchange_code=request.exchange_code,
                symbol=request.symbol,
                current_price=request.current_price,
                news_limit=request.news_limit,
                disclosure_limit=(
                    request.disclosure_limit
                ),
                lookback_days=request.lookback_days,
            )
        )
    except (
        ValueError,
        LookupError,
        RuntimeError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
