from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

class PendingOrderStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

@dataclass(frozen=True, slots=True)
class PendingOrderSnapshot:
    broker_code: str
    account_number: str
    broker_order_id: str
    exchange_code: str
    symbol: str
    name: str
    side: str
    order_type: str
    order_quantity: Decimal
    order_price: Decimal | None
    filled_quantity: Decimal
    remaining_quantity: Decimal
    average_fill_price: Decimal | None
    status: PendingOrderStatus
    ordered_at: datetime | None
    synchronized_at: datetime
    raw_data: dict[str, Any]
