from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class BrokerEnvironment(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class BrokerOrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class BrokerOrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class BrokerOrderStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class BrokerOrderRequest:
    client_order_id: str
    exchange_code: str
    symbol: str
    side: BrokerOrderSide
    order_type: BrokerOrderType
    quantity: Decimal
    price: Decimal | None = None
    account_id: int | None = None
    time_in_force: str = "DAY"


@dataclass(frozen=True, slots=True)
class BrokerOrderResult:
    accepted: bool
    status: BrokerOrderStatus
    broker_order_id: str | None
    submitted_at: datetime
    reject_code: str | None = None
    reject_message: str | None = None
