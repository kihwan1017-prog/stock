from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.operation.calendar_repository import (
    TradingCalendarRepository,
)
from stock_platform.operation.calendar_service import (
    TradingCalendarService,
)


router = APIRouter(
    prefix="/api/v1/trading-calendar",
    tags=["Trading Calendar"],
)


class CalendarDayInput(BaseModel):
    calendar_date: date
    is_trading_day: bool
    holiday_name: str | None = Field(
        default=None,
        max_length=200,
    )
    source_code: str = Field(
        default="MANUAL",
        min_length=1,
        max_length=30,
    )


class CalendarImportRequest(BaseModel):
    exchange_code: str = Field(
        min_length=1,
        max_length=20,
    )
    days: list[CalendarDayInput]


@router.post("/import")
def import_calendar_days(
    request: CalendarImportRequest,
    session: Session = Depends(get_db_session),
):
    rows = [
        {
            "exchange_code": (
                request.exchange_code.upper()
            ),
            "calendar_date": item.calendar_date,
            "is_trading_day": item.is_trading_day,
            "holiday_name": item.holiday_name,
            "source_code": item.source_code.upper(),
        }
        for item in request.days
    ]

    saved_count = TradingCalendarRepository(
        session
    ).upsert_days(rows)

    return {
        "exchange_code": request.exchange_code.upper(),
        "saved_count": saved_count,
    }


@router.get("/{exchange_code}/{calendar_date}")
def evaluate_calendar_day(
    exchange_code: str,
    calendar_date: date,
    session: Session = Depends(get_db_session),
):
    return TradingCalendarService(
        TradingCalendarRepository(session)
    ).evaluate(
        exchange_code=exchange_code,
        calendar_date=calendar_date,
    )


@router.get(
    "/{exchange_code}/{calendar_date}/previous"
)
def get_previous_trading_day(
    exchange_code: str,
    calendar_date: date,
    session: Session = Depends(get_db_session),
):
    try:
        result = TradingCalendarService(
            TradingCalendarRepository(session)
        ).previous_trading_day(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return {"trading_date": result}


@router.get(
    "/{exchange_code}/{calendar_date}/next"
)
def get_next_trading_day(
    exchange_code: str,
    calendar_date: date,
    session: Session = Depends(get_db_session),
):
    try:
        result = TradingCalendarService(
            TradingCalendarRepository(session)
        ).next_trading_day(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return {"trading_date": result}
