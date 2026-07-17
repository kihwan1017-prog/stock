from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

@dataclass(frozen=True, slots=True)
class MarketSymbol:
    market: str
    symbol: str
    name: str
    currency: str
    active: bool = True

@dataclass(frozen=True, slots=True)
class Quote:
    market: str
    symbol: str
    price: Decimal
    change: Decimal | None
    change_rate: Decimal | None
    volume: Decimal | None
    quoted_at: datetime

@dataclass(frozen=True, slots=True)
class Trade:
    market: str
    symbol: str
    trade_id: str
    price: Decimal
    quantity: Decimal
    side: str | None
    traded_at: datetime

@dataclass(frozen=True, slots=True)
class DailyCandle:
    market: str
    symbol: str
    candle_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    trade_amount: Decimal | None = None
