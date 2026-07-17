from datetime import datetime, timezone
from decimal import Decimal
import httpx

from stock_platform.market.models import DailyCandle, MarketSymbol, Quote

class UpbitMarketClient:
    def __init__(self, base_url: str = "https://api.upbit.com", timeout_seconds: float = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def list_markets(self) -> list[MarketSymbol]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/v1/market/all", params={"isDetails": "true"})
            response.raise_for_status()
        result = []
        for row in response.json():
            code = row["market"]
            currency = code.split("-", 1)[0]
            result.append(MarketSymbol("UPBIT", code, row.get("korean_name") or row.get("english_name") or code, currency))
        return result

    async def get_quote(self, symbol: str) -> Quote:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/v1/ticker", params={"markets": symbol})
            response.raise_for_status()
        row = response.json()[0]
        return Quote(
            market="UPBIT",
            symbol=symbol,
            price=Decimal(str(row["trade_price"])),
            change=Decimal(str(row.get("signed_change_price", 0))),
            change_rate=Decimal(str(row.get("signed_change_rate", 0))),
            volume=Decimal(str(row.get("acc_trade_volume_24h", 0))),
            quoted_at=datetime.fromtimestamp(row["timestamp"] / 1000, tz=timezone.utc),
        )

    async def get_daily_candles(self, symbol: str, count: int = 200, to: str | None = None) -> list[DailyCandle]:
        params = {"market": symbol, "count": min(count, 200)}
        if to:
            params["to"] = to
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/v1/candles/days", params=params)
            response.raise_for_status()
        result = []
        for row in response.json():
            result.append(DailyCandle(
                market="UPBIT",
                symbol=symbol,
                candle_date=datetime.fromisoformat(row["candle_date_time_kst"]).date(),
                open_price=Decimal(str(row["opening_price"])),
                high_price=Decimal(str(row["high_price"])),
                low_price=Decimal(str(row["low_price"])),
                close_price=Decimal(str(row["trade_price"])),
                volume=Decimal(str(row["candle_acc_trade_volume"])),
                trade_amount=Decimal(str(row["candle_acc_trade_price"])),
            ))
        return result
