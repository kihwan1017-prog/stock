from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.operation.report_repository import (
    DailyOperationsReportRepository,
)
from stock_platform.operation.report_service import (
    DailyOperationsReportService,
)


router = APIRouter(
    prefix="/api/v1/daily-reports",
    tags=["Daily Reports"],
)


class DailyReportGenerateRequest(BaseModel):
    report_date: date
    exchange_code: str = Field(
        default="KRX",
        min_length=1,
        max_length=20,
    )
    paper_account_id: int | None = Field(
        default=None,
        gt=0,
    )
    current_prices: dict[str, Decimal] = Field(
        default_factory=dict
    )


@router.post("")
def generate_daily_report(
    request: DailyReportGenerateRequest,
    session: Session = Depends(get_db_session),
):
    return DailyOperationsReportService(
        session
    ).generate(
        report_date=request.report_date,
        exchange_code=request.exchange_code,
        paper_account_id=request.paper_account_id,
        current_prices={
            key.upper(): value
            for key, value in request.current_prices.items()
        },
    )


@router.get("/{report_date}/{exchange_code}")
def get_daily_report(
    report_date: date,
    exchange_code: str,
    session: Session = Depends(get_db_session),
):
    report = DailyOperationsReportRepository(
        session
    ).get(
        report_date=report_date,
        exchange_code=exchange_code,
    )

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Daily report not found",
        )

    return report


@router.get("")
def list_daily_reports(
    exchange_code: str | None = None,
    limit: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_db_session),
):
    return DailyOperationsReportRepository(
        session
    ).list_recent(
        exchange_code=exchange_code,
        limit=limit,
    )
