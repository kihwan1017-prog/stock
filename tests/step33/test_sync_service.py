from datetime import date
from decimal import Decimal
import pytest

from stock_platform.market.models import DailyCandle
from stock_platform.market.repository import InMemoryMarketRepository
from stock_platform.market.services.sync import DailyCandleSyncService

class FakeUpbit:
    async def get_daily_candles(self, symbol: str, count: int = 200):
        return [DailyCandle("UPBIT", symbol, date(2026, 7, 17),
                            Decimal("1"), Decimal("2"), Decimal("1"), Decimal("2"),
                            Decimal("100"), Decimal("200"))]

@pytest.mark.asyncio
async def test_upbit_sync():
    repo = InMemoryMarketRepository()
    service = DailyCandleSyncService(repo, upbit=FakeUpbit())
    saved = await service.sync_upbit("KRW-BTC")
    assert saved == 1
    assert repo.latest("UPBIT", "KRW-BTC") is not None
