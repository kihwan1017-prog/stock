from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class KiwoomOrderEventType(StrEnum):
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class KiwoomOrderExecutionEvent:
    account_number: str
    broker_order_id: str
    original_order_id: str | None
    exchange_code: str
    symbol: str
    side: str
    event_type: KiwoomOrderEventType
    order_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    fill_price: Decimal | None
    average_fill_price: Decimal | None
    event_time: datetime
    received_at: datetime
    raw_data: dict[str, Any]
