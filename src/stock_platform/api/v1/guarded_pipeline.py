from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.scheduler.guarded_pipeline import (
    TradingDayGuardedPipeline,
)


router = APIRouter(
    prefix="/api/v1/guarded-pipelines",
    tags=["Guarded Pipelines"],
)


class GuardedPipelineRequest(BaseModel):
    exchange_code: str = Field(
        default="KRX",
        min_length=1,
        max_length=20,
    )
    as_of_date: date
    trigger_type: str = Field(
        default="MANUAL",
        min_length=1,
        max_length=30,
    )
    retry_delay_seconds: float = Field(
        default=5.0,
        ge=0,
        le=300,
    )


@router.post("/daily-strategy")
async def execute_guarded_daily_pipeline(
    request: GuardedPipelineRequest,
    session: Session = Depends(get_db_session),
):
    return await TradingDayGuardedPipeline(
        session
    ).execute(
        exchange_code=request.exchange_code,
        as_of_date=request.as_of_date,
        trigger_type=request.trigger_type,
        retry_delay_seconds=(
            request.retry_delay_seconds
        ),
    )
