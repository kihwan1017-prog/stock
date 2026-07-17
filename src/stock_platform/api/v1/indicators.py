from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.indicators.pipeline_service import (
    IndicatorPipelineService,
)
from stock_platform.indicators.repository import (
    IndicatorDailyRepository,
)
from stock_platform.indicators.service import IndicatorService
from stock_platform.markets.quality_service import (
    MarketDataQualityService,
)
from stock_platform.markets.repository import (
    InstrumentRepository,
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    InstrumentService,
    PriceDailyService,
)
from stock_platform.operation.job_repository import (
    JobRunRepository,
)
from stock_platform.operation.job_service import (
    JobExecutionService,
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
    high_52w: Decimal | None = None
    low_52w: Decimal | None = None
    status_code: str = "PARTIAL"
    missing_fields: list[str] = Field(default_factory=list)


class IndicatorComputeRequest(BaseModel):
    start_date: date
    end_date: date


class IndicatorBatchRequest(BaseModel):
    start_date: date
    end_date: date
    exchange_code: str | None = None
    symbol_limit: int | None = Field(default=None, ge=1)


def _pipeline(session: Session) -> IndicatorPipelineService:
    instrument_service = InstrumentService(
        InstrumentRepository(session)
    )
    return IndicatorPipelineService(
        price_service=PriceDailyService(
            PriceDailyRepository(session),
            instrument_service=instrument_service,
        ),
        indicator_repository=IndicatorDailyRepository(session),
        instrument_service=instrument_service,
    )


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
        rows = indicator_service.calculate_daily(
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

    return [
        DailyIndicatorResponse(
            trade_date=item.trade_date,
            close_price=item.close_price,
            volume=item.volume,
            ma5=item.ma5,
            ma20=item.ma20,
            ma60=item.ma60,
            ema12=item.ema12,
            ema26=item.ema26,
            rsi14=item.rsi14,
            macd=item.macd,
            macd_signal=item.macd_signal,
            macd_histogram=item.macd_histogram,
            bollinger_middle=item.bollinger_middle,
            bollinger_upper=item.bollinger_upper,
            bollinger_lower=item.bollinger_lower,
            atr14=item.atr14,
            volume_ma20=item.volume_ma20,
            high_52w=item.high_52w,
            low_52w=item.low_52w,
            status_code=item.status_code,
            missing_fields=list(item.missing_fields),
        )
        for item in rows
    ]


@router.post("/daily/{exchange_code}/{symbol}/compute")
def compute_and_save_indicators(
    exchange_code: str,
    symbol: str,
    request: IndicatorComputeRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        result = _pipeline(session).compute_and_save(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            start_date=request.start_date,
            end_date=request.end_date,
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

    return result.to_dict()


@router.post("/daily/batch/compute")
async def compute_indicators_batch(
    request: IndicatorBatchRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    job_service = JobExecutionService(JobRunRepository(session))
    pipeline = _pipeline(session)

    def _run():
        return pipeline.compute_batch(
            start_date=request.start_date,
            end_date=request.end_date,
            exchange_code=(
                request.exchange_code.upper()
                if request.exchange_code
                else None
            ),
            symbol_limit=request.symbol_limit,
        )

    try:
        history, result = await job_service.execute(
            job_name="indicator_daily_batch",
            job_group="MARKET",
            trigger_type="MANUAL",
            request_payload=request.model_dump(mode="json"),
            handler=_run,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "job_run_id": history.job_run_id,
        "status_code": history.status_code,
        "duration_ms": history.duration_ms,
        "result": result.to_dict(),
    }


@router.get("/daily/{exchange_code}/{symbol}/saved")
def list_saved_indicators(
    exchange_code: str,
    symbol: str,
    start_date: date = Query(...),
    end_date: date = Query(...),
    session: Session = Depends(get_db_session),
):
    try:
        rows = _pipeline(session).list_saved(
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

    return [
        {
            "trade_date": row.trade_date,
            "close_price": row.close_price,
            "volume": row.volume,
            "ma5": row.ma5,
            "ma20": row.ma20,
            "ma60": row.ma60,
            "ema12": row.ema12,
            "ema26": row.ema26,
            "rsi14": row.rsi14,
            "volume_ma20": row.volume_ma20,
            "high_52w": row.high_52w,
            "low_52w": row.low_52w,
            "status_code": row.status_code,
            "missing_fields": row.missing_fields,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]
