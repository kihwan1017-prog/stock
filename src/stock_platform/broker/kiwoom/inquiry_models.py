from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class KiwoomPendingOrder:
    broker_order_id: str
    symbol: str
    side_code: str | None
    order_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    order_price: Decimal | None
    raw_payload: dict


@dataclass(frozen=True, slots=True)
class KiwoomExecution:
    broker_order_id: str
    symbol: str
    execution_number: str | None
    execution_quantity: Decimal
    execution_price: Decimal
    raw_payload: dict


@dataclass(frozen=True, slots=True)
class KiwoomInquiryPage:
    items: list
    has_next: bool
    next_key: str | None
