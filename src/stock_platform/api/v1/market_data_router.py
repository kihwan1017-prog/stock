"""PostgreSQL 기반 market 조회 API.

표준 저장소: market.instrument / price_daily / candle_minute /
quote_snapshot / trade_tick / orderbook_snapshot
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.markets.models import ALLOWED_MINUTE_TIMEFRAMES
from stock_platform.markets.repository import (
    CandleMinuteRepository,
    InstrumentRepository,
    OrderbookSnapshotRepository,
    PriceDailyRepository,
    QuoteSnapshotRepository,
    TradeTickRepository,
)
from stock_platform.markets.service import (
    CandleMinuteService,
    InstrumentNotFoundError,
    InstrumentService,
    OrderbookSnapshotService,
    PriceDailyService,
    QuoteSnapshotService,
    TradeTickService,
)


router = APIRouter(prefix="/api/v1/market", tags=["market-data"])


def _instrument_service(session: Session) -> InstrumentService:
    return InstrumentService(InstrumentRepository(session))


def _price_service(session: Session) -> PriceDailyService:
    instrument_service = _instrument_service(session)
    return PriceDailyService(
        PriceDailyRepository(session),
        instrument_service=instrument_service,
    )


def _candle_service(session: Session) -> CandleMinuteService:
    instrument_service = _instrument_service(session)
    return CandleMinuteService(
        CandleMinuteRepository(session),
        instrument_service=instrument_service,
    )


@router.get("/symbols")
def list_symbols(
    market: str | None = None,
    active_only: bool = True,
    session: Session = Depends(get_db_session),
):
    exchange_code = market.strip().upper() if market else None
    instruments = _instrument_service(session).list(
        exchange_code=exchange_code,
        active_only=active_only,
    )
    return [
        {
            "market": item.exchange_code,
            "symbol": item.symbol,
            "name": item.name,
            "currency": item.currency_code,
            "active": item.is_active,
            "listed_at": item.listed_date,
            "delisted_at": item.delisted_date,
            "asset_type": item.asset_type,
            "updated_at": item.updated_at,
        }
        for item in instruments
    ]


@router.get("/candles/day/{market}/{symbol}")
def get_daily_candles(
    market: str,
    symbol: str,
    limit: int = Query(200, ge=1, le=1000),
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


@router.get("/candles/minute/{market}/{symbol}")
def get_minute_candles(
    market: str,
    symbol: str,
    timeframe: int = Query(1),
    limit: int = Query(200, ge=1, le=1000),
    session: Session = Depends(get_db_session),
):
    if timeframe not in ALLOWED_MINUTE_TIMEFRAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "timeframe must be one of "
                f"{ALLOWED_MINUTE_TIMEFRAMES}"
            ),
        )

    try:
        rows = _candle_service(session).list_recent(
            exchange_code=market.upper(),
            symbol=symbol.upper(),
            timeframe=timeframe,
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
            "timeframe": row.timeframe,
            "candle_at": row.candle_at,
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


@router.get("/quotes/{market}/{symbol}")
def get_quote(
    market: str,
    symbol: str,
    session: Session = Depends(get_db_session),
):
    service = QuoteSnapshotService(
        QuoteSnapshotRepository(session),
        _instrument_service(session),
    )
    try:
        quote = service.get(market.upper(), symbol.upper())
    except InstrumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    if quote is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote snapshot not found",
        )

    return {
        "market": market.upper(),
        "symbol": symbol.upper(),
        "price": quote.trade_price,
        "bid_price": quote.bid_price,
        "ask_price": quote.ask_price,
        "change": quote.change_price,
        "change_rate": quote.change_rate,
        "volume": quote.volume,
        "quoted_at": quote.quoted_at,
        "source": quote.source,
        "updated_at": quote.updated_at,
    }


@router.get("/trades/{market}/{symbol}")
def get_trades(
    market: str,
    symbol: str,
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_db_session),
):
    service = TradeTickService(
        TradeTickRepository(session),
        _instrument_service(session),
    )
    try:
        rows = service.list_recent(
            market.upper(),
            symbol.upper(),
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
            "trade_id": row.trade_id,
            "price": row.price,
            "quantity": row.quantity,
            "side": row.side,
            "traded_at": row.traded_at,
            "source": row.source,
        }
        for row in rows
    ]


@router.get("/orderbook/{market}/{symbol}")
def get_orderbook(
    market: str,
    symbol: str,
    session: Session = Depends(get_db_session),
):
    service = OrderbookSnapshotService(
        OrderbookSnapshotRepository(session),
        _instrument_service(session),
    )
    try:
        row = service.get_latest(market.upper(), symbol.upper())
    except InstrumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Orderbook snapshot not found",
        )

    return {
        "market": market.upper(),
        "symbol": symbol.upper(),
        "captured_at": row.captured_at,
        "bids": row.bids,
        "asks": row.asks,
        "source": row.source,
    }


@router.post("/sync/upbit/day/{symbol}")
async def sync_upbit_daily_alias(
    symbol: str,
    count: int = Query(200, ge=1, le=200),
):
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Use POST /api/v1/upbit/daily/sync with start_date/end_date. "
            f"Requested symbol={symbol}, count={count}"
        ),
    )


@router.post("/sync/kiwoom/day/{symbol}")
async def sync_kiwoom_daily_alias(
    symbol: str,
    base_date: date | None = None,
):
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Use POST /api/v1/sync/kiwoom/daily with start_date/end_date. "
            f"Requested symbol={symbol}, base_date={base_date}"
        ),
    )
