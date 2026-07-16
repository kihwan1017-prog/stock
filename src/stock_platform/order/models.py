from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"

class OrderTimeInForce(StrEnum):
    DAY = "DAY"
    IOC = "IOC"
    FOK = "FOK"

class OrderStatus(StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REPLACE_REQUESTED = "REPLACE_REQUESTED"
    REPLACED = "REPLACED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"

@dataclass(frozen=True, slots=True)
class CreateOrderCommand:
    account_id: int
    broker_code: str
    exchange_code: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None
    time_in_force: OrderTimeInForce = OrderTimeInForce.DAY
    strategy_code: str | None = None
    strategy_deployment_id: int | None = None
    portfolio_id: int | None = None
    position_id: int | None = None
    client_order_id: str | None = None
    metadata_payload: dict[str, Any] | None = None
