from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class BrokerOrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class BrokerOrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class BrokerOrderStatus(StrEnum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class BrokerOrderRequest:
    exchange_code: str
    symbol: str
    side: BrokerOrderSide
    order_type: BrokerOrderType
    quantity: Decimal
    price: Decimal | None
    client_order_id: str


@dataclass(frozen=True, slots=True)
class BrokerOrderResponse:
    broker_order_id: str
    client_order_id: str
    status: BrokerOrderStatus
    accepted_quantity: Decimal
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    message: str | None
    requested_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BrokerAccountSnapshot:
    account_key: str
    cash_balance: Decimal
    available_cash: Decimal
    total_asset_value: Decimal
    currency_code: str
    fetched_at: datetime
