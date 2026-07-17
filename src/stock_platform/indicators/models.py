from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PriceBar:
    trade_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class DailyIndicator:
    trade_date: date
    close_price: Decimal
    volume: Decimal
    ma5: Decimal | None
    ma20: Decimal | None
    ma60: Decimal | None
    ema12: Decimal | None
    ema26: Decimal | None
    rsi14: Decimal | None
    macd: Decimal | None
    macd_signal: Decimal | None
    macd_histogram: Decimal | None
    bollinger_middle: Decimal | None
    bollinger_upper: Decimal | None
    bollinger_lower: Decimal | None
    atr14: Decimal | None
    volume_ma20: Decimal | None
    high_52w: Decimal | None = None
    low_52w: Decimal | None = None
    status_code: str = "PARTIAL"
    missing_fields: tuple[str, ...] = ()


# READY 판정에 필요한 핵심 지표
REQUIRED_INDICATOR_FIELDS: tuple[str, ...] = (
    "ma5",
    "ma20",
    "ma60",
    "ema12",
    "rsi14",
    "volume_ma20",
    "high_52w",
    "low_52w",
)
