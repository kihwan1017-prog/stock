from __future__ import annotations
from typing import Protocol
from .models import DailyCandle, MarketSymbol, Quote, Trade


class SymbolRepository(Protocol):
    def upsert_many(self, symbols: list[MarketSymbol]) -> None: ...
    def list(self, market: str | None = None, active_only: bool = True) -> list[MarketSymbol]: ...

class QuoteRepository(Protocol):
    def upsert(self, quote: Quote) -> Quote: ...
    def get(self, market: str, symbol: str) -> Quote | None: ...

class TradeRepository(Protocol):
    def append_many(self, trades: list[Trade]) -> int: ...
    def list(self, market: str, symbol: str, limit: int = 100) -> list[Trade]: ...

class DailyCandleRepository(Protocol):
    def upsert_many(self, candles: list[DailyCandle]) -> int: ...
    def list(self, market: str, symbol: str, limit: int = 200) -> list[DailyCandle]: ...
    def latest(self, market: str, symbol: str) -> DailyCandle | None: ...

class InMemoryMarketRepository(SymbolRepository, QuoteRepository, TradeRepository, DailyCandleRepository):
    def __init__(self) -> None:
        self.symbols: dict[tuple[str, str], MarketSymbol] = {}
        self.quotes: dict[tuple[str, str], Quote] = {}
        self.trades: dict[tuple[str, str, str], Trade] = {}
        self.candles: dict[tuple[str, str, object], DailyCandle] = {}

    def upsert_many(self, items):
        if not items:
            return 0
        first = items[0]
        if isinstance(first, MarketSymbol):
            for item in items:
                self.symbols[(item.market, item.symbol)] = item
        elif isinstance(first, Trade):
            for item in items:
                self.trades[(item.market, item.symbol, item.trade_id)] = item
        elif isinstance(first, DailyCandle):
            for item in items:
                self.candles[(item.market, item.symbol, item.candle_date)] = item
        else:
            raise TypeError(type(first))
        return len(items)

    def upsert(self, quote: Quote) -> Quote:
        self.quotes[(quote.market, quote.symbol)] = quote
        return quote

    def get(self, market: str, symbol: str) -> Quote | None:
        return self.quotes.get((market, symbol))

    def list(self, market: str | None = None, symbol: str | None = None,
             active_only: bool = True, limit: int = 200):
        if symbol is None:
            values = list(self.symbols.values())
            if market is not None:
                values = [x for x in values if x.market == market]
            return [x for x in values if x.active or not active_only]
        trades = [x for x in self.trades.values() if x.market == market and x.symbol == symbol]
        trades.sort(key=lambda x: x.traded_at, reverse=True)
        if trades:
            return trades[:limit]
        candles = [x for x in self.candles.values() if x.market == market and x.symbol == symbol]
        candles.sort(key=lambda x: x.candle_date, reverse=True)
        return candles[:limit]

    def append_many(self, trades: list[Trade]) -> int:
        return self.upsert_many(trades)

    def latest(self, market: str, symbol: str) -> DailyCandle | None:
        items = [x for x in self.candles.values() if x.market == market and x.symbol == symbol]
        return max(items, key=lambda x: x.candle_date) if items else None
