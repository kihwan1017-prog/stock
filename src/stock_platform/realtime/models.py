from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class MarketEventType(StrEnum):
    TICKER = "TICKER"
    TRADE = "TRADE"
    ORDERBOOK = "ORDERBOOK"


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


@dataclass(frozen=True, slots=True)
class RealtimeTrade:
    exchange_code: str
    symbol: str
    trade_id: str
    price: Decimal
    quantity: Decimal
    side: str | None
    traded_at: datetime
    received_at: datetime
    source_code: str
    event_type: MarketEventType = MarketEventType.TRADE


@dataclass(frozen=True, slots=True)
class RealtimeOrderbook:
    exchange_code: str
    symbol: str
    bids: list[dict[str, Any]]
    asks: list[dict[str, Any]]
    captured_at: datetime
    received_at: datetime
    source_code: str
    event_type: MarketEventType = MarketEventType.ORDERBOOK
