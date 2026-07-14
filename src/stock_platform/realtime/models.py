from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class MarketEventType(StrEnum):
    TICKER = "TICKER"
    TRADE = "TRADE"


@dataclass(frozen=True, slots=True)
class RealtimeQuote:
    exchange_code: str
    symbol: str
    event_type: MarketEventType
    trade_price: Decimal
    opening_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    previous_close_price: Decimal | None
    change_price: Decimal | None
    change_rate: Decimal | None
    accumulated_volume: Decimal | None
    trade_volume: Decimal | None
    event_time: datetime
    received_at: datetime
    source_code: str
