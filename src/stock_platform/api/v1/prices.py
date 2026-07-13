from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.markets.models import PriceDaily
from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)


router = APIRouter(
    prefix="/api/v1/prices",
    tags=["Market Prices"],
)


class PriceDailyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_id: int
    trade_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    trade_value: Decimal
    change_rate: Decimal | None
    source: str


def _get_service(session: Session) -> PriceDailyService:
    return PriceDailyService(PriceDailyRepository(session))


@router.get(
    "/daily/{exchange_code}/{symbol}",
    response_model=list[PriceDailyResponse],
)
def get_daily_prices(
    exchange_code: str,
    symbol: str,
    start_date: date = Query(...),
    end_date: date = Query(...),
    session: Session = Depends(get_db_session),
) -> list[PriceDaily]:
    service = _get_service(session)

    try:
        return service.get_between(
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


@router.get(
    "/latest/{exchange_code}/{symbol}",
    response_model=PriceDailyResponse | None,
)
def get_latest_price(
    exchange_code: str,
    symbol: str,
    session: Session = Depends(get_db_session),
) -> PriceDaily | None:
    service = _get_service(session)

    try:
        return service.get_latest(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
        )
    except InstrumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
