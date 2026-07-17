from dataclasses import dataclass
from datetime import date
from decimal import Decimal

@dataclass(frozen=True, slots=True)
class IndicatorValue:
    market: str
    symbol: str
    trading_date: date
    sma5: Decimal | None = None
    sma20: Decimal | None = None
    ema20: Decimal | None = None
    rsi14: Decimal | None = None
