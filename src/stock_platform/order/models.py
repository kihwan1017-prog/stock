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
    SUBMITTING = "SUBMITTING"
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
    # STEP 8-5-12 — Upbit Ambiguous / Identity
    AMBIGUOUS_SUBMISSION = "AMBIGUOUS_SUBMISSION"
    REMOTE_LOOKUP_PENDING = "REMOTE_LOOKUP_PENDING"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


TERMINAL_ORDER_STATUSES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REPLACED,
        OrderStatus.REJECTED,
        OrderStatus.FAILED,
        OrderStatus.IDENTITY_CONFLICT,
    }
)

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
    strategy_id: int | None = None
    strategy_version: int | None = None
    runtime_scope_hash: str | None = None
    account_strategy_link_id: int | None = None
    user_id: int | None = None
    execution_mode: str | None = None
    portfolio_id: int | None = None
    position_id: int | None = None
    client_order_id: str | None = None
    metadata_payload: dict[str, Any] | None = None
    # STEP8-1 — LIVE 키움·업비트는 UserBrokerAccount FK
    user_broker_account_id: int | None = None
