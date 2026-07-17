from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.markets.repository import (
    InstrumentRepository,
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)
from stock_platform.screener.batch_service import (
    CandidateBatchService,
)
from stock_platform.screener.service import ScreenerService


router = APIRouter(
    prefix="/api/v1/candidates",
    tags=["Candidates"],
)


class RuleResultResponse(BaseModel):
    liquidity: bool
    trade_value: bool
    volume_surge: bool
    trend_alignment: bool
    rsi_range: bool
    week52_position: bool
    atr_acceptable: bool
    tradable: bool
    macd_positive: bool
    breakout: bool
    passed_count: int
    passed: bool
    rejection_reasons: list[str] = Field(default_factory=list)


class ScoreBreakdownResponse(BaseModel):
    liquidity: Decimal
    trade_value: Decimal
    volume: Decimal
    trend: Decimal
    rsi: Decimal
    macd: Decimal
    week52: Decimal
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


class CandidateBatchResponse(BaseModel):
    exchange_code: str
    as_of_date: date
    requested_count: int
    evaluated_count: int
    skipped_count: int
    selected_count: int
    candidates: list[CandidateScoreResponse]


def _serialize_score(score) -> dict:
    return {
        "exchange_code": score.exchange_code,
        "symbol": score.symbol,
        "trade_date": score.trade_date,
        "total_score": score.total_score,
        "rules": score.rules.to_dict(),
        "breakdown": {
            "liquidity": score.breakdown.liquidity,
            "trade_value": score.breakdown.trade_value,
            "volume": score.breakdown.volume,
            "trend": score.breakdown.trend,
            "rsi": score.breakdown.rsi,
            "macd": score.breakdown.macd,
            "week52": score.breakdown.week52,
            "breakout": score.breakdown.breakout,
            "volatility": score.breakdown.volatility,
            "total": score.breakdown.total,
        },
    }


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
    service = ScreenerService(
        price_service,
        instrument_repository=InstrumentRepository(session),
    )

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

    return _serialize_score(score)


@router.get(
    "/top/{exchange_code}",
    response_model=CandidateBatchResponse,
)
def get_top_candidates(
    exchange_code: str,
    as_of_date: date = Query(...),
    limit: int = Query(default=10, ge=1, le=200),
    minimum_score: float = Query(
        default=0,
        ge=0,
        le=100,
    ),
    require_all_rules: bool = Query(default=False),
    session: Session = Depends(get_db_session),
):
    service = CandidateBatchService(session)

    try:
        result = service.screen(
            exchange_code=exchange_code,
            as_of_date=as_of_date,
            limit=limit,
            minimum_score=minimum_score,
            require_all_rules=require_all_rules,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "exchange_code": result.exchange_code,
        "as_of_date": result.as_of_date,
        "requested_count": result.requested_count,
        "evaluated_count": result.evaluated_count,
        "skipped_count": result.skipped_count,
        "selected_count": len(result.selected),
        "candidates": [
            _serialize_score(score)
            for score in result.selected
        ],
    }
