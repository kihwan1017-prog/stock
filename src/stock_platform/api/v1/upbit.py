from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.brokers.upbit.client import (
    UpbitQuotationClient,
)
from stock_platform.brokers.upbit.exceptions import UpbitError
from stock_platform.collectors.upbit.batch_daily_sync_service import (
    UpbitKrwDailyBatchResult,
    UpbitKrwDailyBatchSyncService,
)
from stock_platform.collectors.upbit.daily_collector import (
    UpbitDailyCollectionError,
    UpbitDailyCollector,
)
from stock_platform.collectors.upbit.instrument_sync_service import (
    UpbitInstrumentSyncResult,
    UpbitInstrumentSyncService,
)
from stock_platform.collectors.upbit.minute_collector import (
    UpbitMinuteCollectionError,
    UpbitMinuteCollector,
)
from stock_platform.collectors.upbit.minute_sync_service import (
    UpbitMinuteSyncResult,
    UpbitMinuteSyncService,
)
from stock_platform.collectors.upbit.sync_service import (
    UpbitDailySyncResult,
    UpbitDailySyncService,
)
from stock_platform.database.session import get_db_session
from stock_platform.markets.repository import (
    CandleMinuteRepository,
    InstrumentRepository,
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    CandleMinuteService,
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
    prefix="/api/v1/upbit",
    tags=["Upbit"],
)


class UpbitDailySyncRequest(BaseModel):
    market: str = Field(
        default="KRW-BTC",
        min_length=3,
        max_length=30,
    )
    start_date: date
    end_date: date
    resume: bool = True


class UpbitDailySyncResponse(BaseModel):
    exchange_code: str
    symbol: str
    requested_start_date: date
    requested_end_date: date
    collected_count: int
    saved_count: int


class UpbitKrwDailyBatchRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    lookback_years: int = Field(default=3, ge=1, le=10)
    resume: bool = True
    market_limit: int | None = Field(default=None, ge=1)
    max_retries: int = Field(default=2, ge=0, le=5)
    sync_instruments: bool = True


@router.get("/markets")
async def list_upbit_markets(
    krw_only: bool = True,
) -> list[dict]:
    try:
        async with UpbitQuotationClient() as client:
            markets = await client.list_markets(
                is_details=True
            )
    except UpbitError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    if krw_only:
        markets = [
            item
            for item in markets
            if str(item.get("market", "")).startswith("KRW-")
        ]

    return markets


class UpbitInstrumentSyncResponse(BaseModel):
    exchange_code: str
    requested_count: int
    saved_count: int
    krw_only: bool


@router.post(
    "/instruments/sync",
    response_model=UpbitInstrumentSyncResponse,
)
async def sync_upbit_instruments(
    krw_only: bool = True,
    session: Session = Depends(get_db_session),
) -> UpbitInstrumentSyncResult:
    instrument_service = InstrumentService(
        InstrumentRepository(session)
    )

    try:
        async with UpbitQuotationClient() as client:
            return await UpbitInstrumentSyncService(
                client=client,
                instrument_service=instrument_service,
            ).sync(krw_only=krw_only)
    except UpbitError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post(
    "/daily/sync",
    response_model=UpbitDailySyncResponse,
)
async def sync_upbit_daily(
    request: UpbitDailySyncRequest,
    session: Session = Depends(get_db_session),
) -> UpbitDailySyncResult:
    instrument_service = InstrumentService(
        InstrumentRepository(session)
    )
    price_service = PriceDailyService(
        PriceDailyRepository(session),
        instrument_service=instrument_service,
    )

    try:
        async with UpbitQuotationClient() as client:
            collector = UpbitDailyCollector(client)
            service = UpbitDailySyncService(
                collector=collector,
                price_service=price_service,
                instrument_service=instrument_service,
            )

            return await service.sync(
                market=request.market,
                start_date=request.start_date,
                end_date=request.end_date,
                resume=request.resume,
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
    except (
        UpbitError,
        UpbitDailyCollectionError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/daily/sync/krw-batch")
async def sync_upbit_krw_daily_batch(
    request: UpbitKrwDailyBatchRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """KRW 전체 일봉 동기화. 결과는 job_run_history에 기록한다."""

    instrument_service = InstrumentService(
        InstrumentRepository(session)
    )
    price_service = PriceDailyService(
        PriceDailyRepository(session),
        instrument_service=instrument_service,
    )
    job_service = JobExecutionService(
        JobRunRepository(session)
    )

    async def _run() -> UpbitKrwDailyBatchResult:
        async with UpbitQuotationClient() as client:
            return await UpbitKrwDailyBatchSyncService(
                instrument_sync=UpbitInstrumentSyncService(
                    client=client,
                    instrument_service=instrument_service,
                ),
                daily_sync=UpbitDailySyncService(
                    collector=UpbitDailyCollector(client),
                    price_service=price_service,
                    instrument_service=instrument_service,
                ),
                instrument_service=instrument_service,
            ).sync(
                start_date=request.start_date,
                end_date=request.end_date,
                lookback_years=request.lookback_years,
                resume=request.resume,
                market_limit=request.market_limit,
                max_retries=request.max_retries,
                sync_instruments=request.sync_instruments,
            )

    try:
        history, result = await job_service.execute(
            job_name="upbit_krw_daily_sync",
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
    except (
        UpbitError,
        UpbitDailyCollectionError,
        RuntimeError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return {
        "job_run_id": history.job_run_id,
        "job_name": history.job_name,
        "status_code": history.status_code,
        "duration_ms": history.duration_ms,
        "result": result.to_dict(),
    }


class UpbitMinuteSyncRequest(BaseModel):
    market: str = Field(default="KRW-BTC", min_length=3, max_length=30)
    timeframe: int = Field(default=1)
    start_at: datetime
    end_at: datetime
    resume: bool = True


class UpbitMinuteSyncResponse(BaseModel):
    exchange_code: str
    symbol: str
    timeframe: int
    requested_start_at: datetime
    requested_end_at: datetime
    collected_count: int
    saved_count: int


@router.post(
    "/minute/sync",
    response_model=UpbitMinuteSyncResponse,
)
async def sync_upbit_minute(
    request: UpbitMinuteSyncRequest,
    session: Session = Depends(get_db_session),
) -> UpbitMinuteSyncResult:
    instrument_service = InstrumentService(
        InstrumentRepository(session)
    )
    candle_service = CandleMinuteService(
        CandleMinuteRepository(session),
        instrument_service=instrument_service,
    )

    try:
        async with UpbitQuotationClient() as client:
            return await UpbitMinuteSyncService(
                collector=UpbitMinuteCollector(client),
                candle_service=candle_service,
                instrument_service=instrument_service,
            ).sync(
                market=request.market,
                timeframe=request.timeframe,
                start_at=request.start_at,
                end_at=request.end_at,
                resume=request.resume,
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
    except (
        UpbitError,
        UpbitMinuteCollectionError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
