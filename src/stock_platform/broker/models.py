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
    CANCELLED = "CANCELLED"
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
    """기존 OrderDispatcher / Kiwoom sync 어댑터용 결과."""

    accepted: bool
    status: BrokerOrderStatus
    broker_order_id: str | None
    submitted_at: datetime
    reject_code: str | None = None
    reject_message: str | None = None


@dataclass(frozen=True, slots=True)
class BrokerOrderResponse:
    """공통 BrokerOrderAdapter용 주문 응답."""

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
    """공통 BrokerOrderAdapter용 계좌 스냅샷."""

    account_key: str
    cash_balance: Decimal
    available_cash: Decimal
    total_asset_value: Decimal
    currency_code: str
    fetched_at: datetime
