from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.markets.quality_service import (
    MarketDataQualityService,
)


router = APIRouter(
    prefix="/api/v1/market-quality",
    tags=["Market Quality"],
)


class QualityCheckRequest(BaseModel):
    exchange_code: str | None = None
    lookback_days: int = Field(default=90, ge=1, le=730)
    max_gap_days: int | None = Field(default=None, ge=1)
    symbol_limit: int = Field(default=500, ge=1, le=5000)


@router.get("/dashboard")
def market_collection_dashboard(
    session: Session = Depends(get_db_session),
):
    """시장별 최신 수집 시각 Dashboard."""

    return {
        "latest_by_exchange": MarketDataQualityService(
            session
        ).latest_collection_dashboard()
    }


@router.post("/check")
def run_quality_check(
    request: QualityCheckRequest,
    session: Session = Depends(get_db_session),
):
    try:
        report = MarketDataQualityService(session).run(
            exchange_code=(
                request.exchange_code.upper()
                if request.exchange_code
                else None
            ),
            lookback_days=request.lookback_days,
            max_gap_days=request.max_gap_days,
            symbol_limit=request.symbol_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return report.to_dict()
