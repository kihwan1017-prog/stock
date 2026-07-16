from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

class BrokerEnvironment(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"

class BrokerOrderStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"

@dataclass(frozen=True, slots=True)
class BrokerOrderRequest:
    client_order_id: str
    account_id: int
    exchange_code: str
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    price: Decimal | None
    time_in_force: str

@dataclass(frozen=True, slots=True)
class BrokerOrderResult:
    accepted: bool
    status: BrokerOrderStatus
    broker_order_id: str | None
    submitted_at: datetime
    reject_code: str | None = None
    reject_message: str | None = None
