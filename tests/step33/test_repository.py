from datetime import date, datetime, timezone
from decimal import Decimal
from stock_platform.market.models import DailyCandle, MarketSymbol, Quote
from stock_platform.market.repository import InMemoryMarketRepository

def test_symbol_and_quote_repository():
    repo = InMemoryMarketRepository()
    repo.upsert_many([MarketSymbol("KRX", "005930", "삼성전자", "KRW")])
    assert repo.list(market="KRX")[0].symbol == "005930"

    quote = Quote("KRX", "005930", Decimal("70000"), None, None, None, datetime.now(timezone.utc))
    repo.upsert(quote)
    assert repo.get("KRX", "005930") == quote

def test_daily_candle_latest():
    repo = InMemoryMarketRepository()
    repo.upsert_many([
        DailyCandle("KRX", "005930", date(2026, 7, 16),
                    Decimal("1"), Decimal("2"), Decimal("1"), Decimal("2"), Decimal("100")),
        DailyCandle("KRX", "005930", date(2026, 7, 17),
                    Decimal("2"), Decimal("3"), Decimal("2"), Decimal("3"), Decimal("200")),
    ])
    assert repo.latest("KRX", "005930").candle_date == date(2026, 7, 17)
