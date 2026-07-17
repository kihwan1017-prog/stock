from datetime import date
from fastapi import APIRouter, HTTPException, Query

from stock_platform.market.repository import InMemoryMarketRepository
from stock_platform.market.services.sync import DailyCandleSyncService

router = APIRouter(prefix="/api/v1/market", tags=["market-data"])
repository = InMemoryMarketRepository()
sync_service = DailyCandleSyncService(repository)

@router.get("/symbols")
def list_symbols(market: str | None = None, active_only: bool = True):
    return repository.list(market=market, active_only=active_only)

@router.get("/quotes/{market}/{symbol}")
def get_quote(market: str, symbol: str):
    quote = repository.get(market, symbol)
    if quote is None:
        raise HTTPException(status_code=404, detail="quote not found")
    return quote

@router.get("/candles/day/{market}/{symbol}")
def get_daily_candles(market: str, symbol: str, limit: int = Query(200, ge=1, le=1000)):
    return repository.list(market=market, symbol=symbol, limit=limit)

@router.get("/trades/{market}/{symbol}")
def get_trades(market: str, symbol: str, limit: int = Query(100, ge=1, le=1000)):
    return repository.list(market=market, symbol=symbol, limit=limit)

@router.post("/sync/upbit/day/{symbol}")
async def sync_upbit_daily(symbol: str, count: int = Query(200, ge=1, le=200)):
    try:
        return {"saved": await sync_service.sync_upbit(symbol, count)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.post("/sync/kiwoom/day/{symbol}")
async def sync_kiwoom_daily(symbol: str, base_date: date | None = None):
    try:
        return {"saved": await sync_service.sync_kiwoom(symbol, base_date)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
