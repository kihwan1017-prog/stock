from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.brokers.upbit.client import (
    UpbitQuotationClient,
)
from stock_platform.brokers.upbit.exceptions import UpbitError
from stock_platform.collectors.upbit.daily_collector import (
    UpbitDailyCollectionError,
    UpbitDailyCollector,
)
from stock_platform.collectors.upbit.sync_service import (
    UpbitDailySyncResult,
    UpbitDailySyncService,
)
from stock_platform.database.session import get_db_session
from stock_platform.markets.repository import (
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
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


@router.post(
    "/daily/sync",
    response_model=UpbitDailySyncResponse,
)
async def sync_upbit_daily(
    request: UpbitDailySyncRequest,
    session: Session = Depends(get_db_session),
) -> UpbitDailySyncResult:
    price_service = PriceDailyService(
        PriceDailyRepository(session)
    )

    try:
        async with UpbitQuotationClient() as client:
            collector = UpbitDailyCollector(client)
            service = UpbitDailySyncService(
                collector=collector,
                price_service=price_service,
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
