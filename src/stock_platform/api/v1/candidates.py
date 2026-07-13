from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.markets.repository import (
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)
from stock_platform.screener.service import CandidateService


router = APIRouter(
    prefix="/api/v1/candidates",
    tags=["Candidates"],
)


class RuleResultResponse(BaseModel):
    volume_surge: bool
    trend_alignment: bool
    rsi_range: bool
    macd_positive: bool
    breakout: bool
    atr_acceptable: bool
    passed_count: int
    passed: bool


class ScoreBreakdownResponse(BaseModel):
    volume: Decimal
    trend: Decimal
    rsi: Decimal
    macd: Decimal
    breakout: Decimal
    volatility: Decimal
    total: Decimal


class CandidateScoreResponse(BaseModel):
    exchange_code: str
    symbol: str
    trade_date: date
    total_score: Decimal
    rules: RuleResultResponse
    breakdown: ScoreBreakdownResponse


@router.get(
    "/evaluate/{exchange_code}/{symbol}",
    response_model=CandidateScoreResponse,
)
def evaluate_candidate(
    exchange_code: str,
    symbol: str,
    as_of_date: date = Query(...),
    session: Session = Depends(get_db_session),
):
    price_service = PriceDailyService(
        PriceDailyRepository(session)
    )
    service = CandidateService(price_service)

    try:
        score = service.evaluate(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            as_of_date=as_of_date,
        )
    except InstrumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "exchange_code": score.exchange_code,
        "symbol": score.symbol,
        "trade_date": score.trade_date,
        "total_score": score.total_score,
        "rules": {
            "volume_surge": score.rules.volume_surge,
            "trend_alignment": score.rules.trend_alignment,
            "rsi_range": score.rules.rsi_range,
            "macd_positive": score.rules.macd_positive,
            "breakout": score.rules.breakout,
            "atr_acceptable": score.rules.atr_acceptable,
            "passed_count": score.rules.passed_count,
            "passed": score.rules.passed,
        },
        "breakdown": {
            "volume": score.breakdown.volume,
            "trend": score.breakdown.trend,
            "rsi": score.breakdown.rsi,
            "macd": score.breakdown.macd,
            "breakout": score.breakdown.breakout,
            "volatility": score.breakdown.volatility,
            "total": score.breakdown.total,
        },
    }
