"""Admin Market Data Explorer API."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.markets.collection_status_service import (
    MarketDataCollectionStatusService,
)
from stock_platform.markets.gap_detection_service import MarketDataGapDetectionService
from stock_platform.markets.models import ALLOWED_MINUTE_TIMEFRAMES
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


router = APIRouter(
    prefix="/api/v1/admin/market-data",
    tags=["admin-market-data"],
    dependencies=[Depends(require_admin)],
)


def _status_service(session: Session) -> MarketDataCollectionStatusService:
    return MarketDataCollectionStatusService(session)


def _price_service(session: Session) -> PriceDailyService:
    instrument_service = InstrumentService(InstrumentRepository(session))
    return PriceDailyService(
        PriceDailyRepository(session),
        instrument_service=instrument_service,
    )


def _candle_service(session: Session) -> CandleMinuteService:
    instrument_service = InstrumentService(InstrumentRepository(session))
    return CandleMinuteService(
        CandleMinuteRepository(session),
        instrument_service=instrument_service,
    )


def _normalize_market(market: str) -> str:
    raw = market.strip().upper()
    if raw in {"KIWOOM", "KRX", "STOCK", "STOCKS"}:
        return "KRX"
    if raw in {"UPBIT", "CRYPTO"}:
        return "UPBIT"
    return raw


@router.get("/symbols")
def list_symbols(
    market: str = Query(..., description="UPBIT | KIWOOM(KRX)"),
    q: str | None = Query(default=None),
    active_only: bool = True,
    limit: int = Query(default=500, ge=1, le=5000),
    session: Session = Depends(get_db_session),
):
    exchange_code = _normalize_market(market)
    service = InstrumentService(InstrumentRepository(session))

    if q and q.strip():
        from stock_platform.trading.watchlist_service import WatchlistService

        items = WatchlistService(session).search_symbols(
            query=q.strip(),
            market=exchange_code,
            limit=min(limit, 50),
        )
        return {"items": items, "total": len(items)}

    instruments = service.list(
        exchange_code=exchange_code,
        active_only=active_only,
        limit=limit,
    )
    return {
        "items": [
            {
                "market": item.exchange_code,
                "symbol": item.symbol,
                "name": item.name,
                "currency": item.currency_code,
                "active": item.is_active,
                "asset_type": item.asset_type,
            }
            for item in instruments
        ],
        "total": len(instruments),
    }


@router.get("/symbols/{market}/{symbol}/info")
def symbol_info(
    market: str,
    symbol: str,
    session: Session = Depends(get_db_session),
):
    exchange_code = _normalize_market(market)
    try:
        return _status_service(session).symbol_coverage(exchange_code, symbol)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/candles")
def get_candles(
    market: str = Query(...),
    symbol: str = Query(...),
    timeframe: str = Query(default="day"),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    year: int | None = Query(default=None, ge=2000, le=2100),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_db_session),
):
    exchange_code = _normalize_market(market)
    normalized_symbol = symbol.strip().upper()
    tf = timeframe.strip().lower()

    if year is not None:
        from_date = date(year, 1, 1)
        to_date = date(year, 12, 31)

    if tf in {"day", "daily", "d"}:
        price_service = _price_service(session)
        try:
            if from_date and to_date:
                rows = price_service.get_between(
                    exchange_code=exchange_code,
                    symbol=normalized_symbol,
                    start_date=from_date,
                    end_date=to_date,
                )
            else:
                rows = price_service.list_recent(
                    exchange_code=exchange_code,
                    symbol=normalized_symbol,
                    limit=limit,
                )
        except InstrumentNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

        candles = [
            {
                "market": exchange_code,
                "symbol": normalized_symbol,
                "candle_date": row.trade_date,
                "open_price": row.open_price,
                "high_price": row.high_price,
                "low_price": row.low_price,
                "close_price": row.close_price,
                "volume": row.volume,
                "trade_amount": row.trade_value,
                "change_rate": row.change_rate,
                "source": row.source,
            }
            for row in rows
        ]
        return {
            "timeframe": "day",
            "row_count": len(candles),
            "first_date": candles[0]["candle_date"] if candles else None,
            "last_date": candles[-1]["candle_date"] if candles else None,
            "items": candles,
        }

    if tf in {"minute", "min", "m"}:
        minute_tf = 1
        if minute_tf not in ALLOWED_MINUTE_TIMEFRAMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid minute timeframe",
            )
        try:
            rows = _candle_service(session).list_recent(
                exchange_code=exchange_code,
                symbol=normalized_symbol,
                timeframe=minute_tf,
                limit=min(limit, 1000),
            )
        except InstrumentNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

        if not rows and exchange_code == "KRX":
            return {
                "timeframe": "minute",
                "row_count": 0,
                "policy_message": (
                    "현재 이 시장은 분봉 장기 저장을 사용하지 않습니다."
                ),
                "items": [],
            }

        items = [
            {
                "market": exchange_code,
                "symbol": normalized_symbol,
                "timeframe": row.timeframe,
                "candle_at": row.candle_at,
                "open_price": row.open_price,
                "high_price": row.high_price,
                "low_price": row.low_price,
                "close_price": row.close_price,
                "volume": row.volume,
                "trade_amount": row.trade_value,
            }
            for row in rows
        ]
        return {
            "timeframe": "minute",
            "row_count": len(items),
            "first_date": items[0]["candle_at"] if items else None,
            "last_date": items[-1]["candle_at"] if items else None,
            "items": items,
        }

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="timeframe must be day or minute",
    )


@router.get("/status")
def collection_status(session: Session = Depends(get_db_session)):
    service = _status_service(session)
    root = {
        key: asdict(value) for key, value in service.root_cause_report().items()
    }
    return {
        "root_cause": root,
        "UPBIT_DAILY_JOB_REGISTERED": True,
        "KIWOOM_DAILY_JOB_REGISTERED": True,
        "collection_jobs": service.collection_status(),
        "intraday_policy": asdict(service.intraday_policy()),
    }


@router.get("/quality")
def data_quality(
    market: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
):
    service = _status_service(session)
    rows = service.quality_dashboard()
    if market:
        ex = _normalize_market(market)
        rows = [row for row in rows if row.exchange_code == ex]
    return {
        "items": [asdict(row) for row in rows],
        "checked_at": date.today().isoformat(),
    }


@router.get("/gaps")
def daily_gaps(
    market: str = Query(...),
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    symbol_limit: int = Query(default=30, ge=1, le=200),
    session: Session = Depends(get_db_session),
):
    exchange_code = _normalize_market(market)
    gaps = MarketDataGapDetectionService(session).detect_daily_gaps(
        exchange_code=exchange_code,
        start_date=from_date,
        end_date=to_date,
        symbol_limit=symbol_limit,
    )
    return {"items": gaps, "total": len(gaps)}
