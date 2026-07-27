"""회원용 시장 데이터 조회 API — 주식·업비트 공통.

관리자 전용(/market, /prices, /indicators, /realtime-quotes)과 동일한
서비스 계층을 재사용하는 얇은 읽기 전용 wrapper. exchange_code로
KRX/KOSDAQ(주식)와 UPBIT(업비트)를 동일하게 처리한다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.indicators.service import IndicatorService
from stock_platform.markets.models import PriceDaily
from stock_platform.markets.repository import (
    InstrumentRepository,
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    InstrumentService,
    PriceDailyService,
)
from stock_platform.realtime.manager import realtime_manager


router = APIRouter(
    prefix="/api/v1/user/market",
    tags=["User Market"],
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


def _instrument_service(session: Session) -> InstrumentService:
    return InstrumentService(InstrumentRepository(session))


def _price_service(session: Session) -> PriceDailyService:
    return PriceDailyService(
        PriceDailyRepository(session),
        instrument_service=_instrument_service(session),
    )


@router.get("/symbols")
def list_symbols(
    market: str | None = None,
    q: str | None = Query(
        default=None,
        description="종목코드·이름 검색",
    ),
    active_only: bool = True,
    limit: int = Query(default=500, ge=1, le=2000),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    exchange_code = market.strip().upper() if market else None
    if q and q.strip():
        from stock_platform.trading.watchlist_service import (
            WatchlistService,
        )

        items = WatchlistService(session).search_symbols(
            query=q.strip(),
            market=exchange_code,
            limit=min(limit, 50),
        )
        return [
            {
                "market": item["market"],
                "symbol": item["symbol"],
                "name": item["name"],
                "currency": item.get("currency"),
                "active": True,
                "asset_type": item.get("asset_type"),
            }
            for item in items
        ]

    instruments = _instrument_service(session).list(
        exchange_code=exchange_code,
        active_only=active_only,
        limit=limit,
    )
    return [
        {
            "market": item.exchange_code,
            "symbol": item.symbol,
            "name": item.name,
            "currency": item.currency_code,
            "active": item.is_active,
            "asset_type": item.asset_type,
        }
        for item in instruments
    ]


@router.get(
    "/candles/day/{market}/{symbol}",
)
def get_daily_candles(
    market: str,
    symbol: str,
    limit: int = Query(200, ge=1, le=1000),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        rows = _price_service(session).list_recent(
            exchange_code=market.upper(),
            symbol=symbol.upper(),
            limit=limit,
        )
    except InstrumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return [
        {
            "market": market.upper(),
            "symbol": symbol.upper(),
            "candle_date": row.trade_date,
            "open_price": row.open_price,
            "high_price": row.high_price,
            "low_price": row.low_price,
            "close_price": row.close_price,
            "volume": row.volume,
            "trade_amount": row.trade_value,
            "source": row.source,
        }
        for row in rows
    ]


@router.get(
    "/prices/latest/{exchange_code}/{symbol}",
    response_model=PriceDailyResponse | None,
)
def get_latest_price(
    exchange_code: str,
    symbol: str,
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
) -> PriceDaily | None:
    try:
        return _price_service(session).get_latest(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
        )
    except InstrumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/indicators/daily/{exchange_code}/{symbol}",
    response_model=list[DailyIndicatorResponse],
)
def get_daily_indicators(
    exchange_code: str,
    symbol: str,
    start_date: date = Query(...),
    end_date: date = Query(...),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    indicator_service = IndicatorService(_price_service(session))
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


@router.get("/realtime-quotes")
async def list_latest_quotes(
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
):
    return await realtime_manager.cache.list_all()


@router.get("/realtime-quotes/{exchange_code}/{symbol}")
async def get_latest_quote(
    exchange_code: str,
    symbol: str,
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
):
    quote = await realtime_manager.cache.get(
        exchange_code=exchange_code,
        symbol=symbol,
    )
    if quote is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Realtime quote not found",
        )
    return quote
