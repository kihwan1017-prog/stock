from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from stock_platform.api.deps_admin import require_admin
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.market.exceptions import KiwoomError
from stock_platform.collectors.kiwoom.client_factory import (
    build_kiwoom_market_data_client,
)
from stock_platform.collectors.kiwoom.daily_batch_sync_service import (
    KiwoomDailyBatchResult,
    KiwoomDailyBatchSyncService,
    SCREENER_LOOKBACK_DAYS,
)
from stock_platform.operation.job_repository import JobRunRepository
from stock_platform.operation.job_service import JobExecutionService
from stock_platform.collectors.kiwoom.daily_collector import (
    KiwoomDailyCollectionError,
    KiwoomDailyCollector,
)
from stock_platform.collectors.kiwoom.instrument_collector import (
    DEFAULT_MARKET_TYPES,
    KiwoomInstrumentCollectionError,
    KiwoomInstrumentCollector,
)
from stock_platform.collectors.kiwoom.instrument_sync_service import (
    KiwoomInstrumentSyncResult,
    KiwoomInstrumentSyncService,
)
from stock_platform.collectors.kiwoom.sync_service import (
    KiwoomDailySyncResult,
    KiwoomDailySyncService,
)
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.database.session import get_db_session
from stock_platform.markets.repository import (
    InstrumentRepository,
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    InstrumentService,
    PriceDailyService,
)


router = APIRouter(
    prefix="/api/v1/sync",
    tags=["Synchronization"],
    dependencies=[Depends(require_admin)],
)


class KiwoomDailySyncRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    start_date: date
    end_date: date
    exchange_code: str = Field(default="KRX", min_length=1, max_length=20)
    adjusted_price: bool = True
    resume: bool = True
    use_real_rest: bool = True


class KiwoomDailySyncResponse(BaseModel):
    exchange_code: str
    symbol: str
    requested_start_date: date
    requested_end_date: date
    collected_count: int
    saved_count: int


@router.post(
    "/kiwoom/daily",
    response_model=KiwoomDailySyncResponse,
)
async def sync_kiwoom_daily(
    request: KiwoomDailySyncRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
) -> KiwoomDailySyncResult:
    enforce_rate_limit(
        http_request,
        scope="sync_kiwoom_daily",
        limit=20,
        window_seconds=60,
    )
    instrument_service = InstrumentService(
        InstrumentRepository(session)
    )
    price_service = PriceDailyService(
        PriceDailyRepository(session),
        instrument_service=instrument_service,
    )

    try:
        async with build_kiwoom_market_data_client(
            use_real_rest=request.use_real_rest,
        ) as client:
            collector = KiwoomDailyCollector(client)
            sync_service = KiwoomDailySyncService(
                collector=collector,
                price_service=price_service,
                instrument_service=instrument_service,
            )

            return await sync_service.sync(
                symbol=request.symbol,
                start_date=request.start_date,
                end_date=request.end_date,
                exchange_code=request.exchange_code,
                adjusted_price=request.adjusted_price,
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
        KiwoomError,
        KiwoomDailyCollectionError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


class KiwoomInstrumentSyncRequest(BaseModel):
    market_types: list[str] | None = None
    max_pages: int = Field(default=100, ge=1, le=500)
    use_real_rest: bool = True


class KiwoomInstrumentSyncResponse(BaseModel):
    requested: int
    received: int
    inserted: int
    updated: int
    skipped: int
    failed: int
    kospi: int
    kosdaq: int
    etf: int
    etn: int
    other: int
    exchange_code: str
    market_types: list[str]


@router.post(
    "/kiwoom/instruments",
    response_model=KiwoomInstrumentSyncResponse,
)
async def sync_kiwoom_instruments(
    request: KiwoomInstrumentSyncRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
) -> KiwoomInstrumentSyncResult:
    enforce_rate_limit(
        http_request,
        scope="sync_kiwoom_instruments",
        limit=5,
        window_seconds=60,
    )
    instrument_service = InstrumentService(InstrumentRepository(session))
    market_types = tuple(request.market_types or DEFAULT_MARKET_TYPES)
    try:
        async with build_kiwoom_market_data_client(
            use_real_rest=request.use_real_rest,
        ) as client:
            collector = KiwoomInstrumentCollector(client)
            sync_service = KiwoomInstrumentSyncService(
                collector=collector,
                instrument_service=instrument_service,
            )
            return await sync_service.sync(
                market_types=market_types,
                max_pages=request.max_pages,
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except (KiwoomError, KiwoomInstrumentCollectionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


class KiwoomDailyBatchSyncRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    lookback_days: int = Field(default=SCREENER_LOOKBACK_DAYS, ge=60, le=800)
    resume: bool = True
    symbol_limit: int | None = Field(default=None, ge=1, le=20000)
    batch_size: int = Field(default=20, ge=1, le=200)
    delay_seconds: float = Field(default=0.2, ge=0, le=5)
    max_retries: int = Field(default=2, ge=0, le=5)
    use_real_rest: bool = True


@router.post("/kiwoom/daily-batch")
async def sync_kiwoom_daily_batch(
    request: KiwoomDailyBatchSyncRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
) -> dict:
    enforce_rate_limit(
        http_request,
        scope="sync_kiwoom_daily_batch",
        limit=2,
        window_seconds=60,
    )
    instrument_service = InstrumentService(InstrumentRepository(session))
    price_service = PriceDailyService(
        PriceDailyRepository(session),
        instrument_service=instrument_service,
    )
    job_service = JobExecutionService(JobRunRepository(session))

    async def _run() -> KiwoomDailyBatchResult:
        async with build_kiwoom_market_data_client(
            use_real_rest=request.use_real_rest,
        ) as client:
            daily_sync = KiwoomDailySyncService(
                collector=KiwoomDailyCollector(client),
                price_service=price_service,
                instrument_service=instrument_service,
            )
            return await KiwoomDailyBatchSyncService(
                daily_sync=daily_sync,
                instrument_service=instrument_service,
            ).sync(
                start_date=request.start_date,
                end_date=request.end_date,
                lookback_days=request.lookback_days,
                resume=request.resume,
                symbol_limit=request.symbol_limit,
                batch_size=request.batch_size,
                delay_seconds=request.delay_seconds,
                max_retries=request.max_retries,
            )

    try:
        history, result = await job_service.execute(
            job_name="kiwoom_krx_daily_sync",
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
    except (KiwoomError, KiwoomDailyCollectionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    payload = result.to_dict()
    payload["job_run_id"] = history.job_run_id
    payload["status_code"] = history.status_code
    return payload
