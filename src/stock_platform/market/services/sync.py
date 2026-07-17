from datetime import date, timedelta
from stock_platform.market.clients.kiwoom import KiwoomMarketClient
from stock_platform.market.clients.upbit import UpbitMarketClient
from stock_platform.market.repository import DailyCandleRepository

class DailyCandleSyncService:
    def __init__(self, repository: DailyCandleRepository,
                 upbit: UpbitMarketClient | None = None,
                 kiwoom: KiwoomMarketClient | None = None) -> None:
        self.repository = repository
        self.upbit = upbit
        self.kiwoom = kiwoom

    async def sync_upbit(self, symbol: str, count: int = 200) -> int:
        if self.upbit is None:
            raise RuntimeError("Upbit client is not configured")
        candles = await self.upbit.get_daily_candles(symbol, count=count)
        return self.repository.upsert_many(candles)

    async def sync_kiwoom(self, symbol: str, base_date: date | None = None) -> int:
        if self.kiwoom is None:
            raise RuntimeError("Kiwoom client is not configured")
        candles = await self.kiwoom.get_daily_candles(symbol, base_date or date.today())
        return self.repository.upsert_many(candles)

    def next_start_date(self, market: str, symbol: str, default_days: int = 1095) -> date:
        latest = self.repository.latest(market, symbol)
        return latest.candle_date + timedelta(days=1) if latest else date.today() - timedelta(days=default_days)
