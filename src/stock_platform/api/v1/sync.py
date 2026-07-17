from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.brokers.kiwoom.client import KiwoomRestClient
from stock_platform.brokers.kiwoom.exceptions import KiwoomError
from stock_platform.collectors.kiwoom.daily_collector import (
    KiwoomDailyCollectionError,
    KiwoomDailyCollector,
)
from stock_platform.collectors.kiwoom.sync_service import (
    KiwoomDailySyncResult,
    KiwoomDailySyncService,
)
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
)


class KiwoomDailySyncRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    start_date: date
    end_date: date
    exchange_code: str = Field(default="KRX", min_length=1, max_length=20)
    adjusted_price: bool = True
    resume: bool = True


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
    session: Session = Depends(get_db_session),
) -> KiwoomDailySyncResult:
    instrument_service = InstrumentService(
        InstrumentRepository(session)
    )
    price_service = PriceDailyService(
        PriceDailyRepository(session),
        instrument_service=instrument_service,
    )

    try:
        async with KiwoomRestClient() as client:
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
