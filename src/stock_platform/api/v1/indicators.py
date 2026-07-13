from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.indicators.service import IndicatorService
from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)


router = APIRouter(
    prefix="/api/v1/indicators",
    tags=["Indicators"],
)


class DailyIndicatorResponse(BaseModel):
    trade_date: date
    close_price: Decimal
    volume: Decimal
    ma5: Decimal | None
    ma20: Decimal | None
    ma60: Decimal | None
    ema12: Decimal | None
    ema26: Decimal | None
    rsi14: Decimal | None
    macd: Decimal | None
    macd_signal: Decimal | None
    macd_histogram: Decimal | None
    bollinger_middle: Decimal | None
    bollinger_upper: Decimal | None
    bollinger_lower: Decimal | None
    atr14: Decimal | None
    volume_ma20: Decimal | None


@router.get(
    "/daily/{exchange_code}/{symbol}",
    response_model=list[DailyIndicatorResponse],
)
def get_daily_indicators(
    exchange_code: str,
    symbol: str,
    start_date: date = Query(...),
    end_date: date = Query(...),
    session: Session = Depends(get_db_session),
):
    price_service = PriceDailyService(
        PriceDailyRepository(session)
    )
    indicator_service = IndicatorService(price_service)

    try:
        return indicator_service.calculate_daily(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            start_date=start_date,
            end_date=end_date,
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
