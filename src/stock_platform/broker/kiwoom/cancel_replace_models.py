from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class KiwoomCancelOrderRequest:
    broker_order_id: str
    exchange_code: str
    symbol: str
    cancel_quantity: Decimal


@dataclass(frozen=True, slots=True)
class KiwoomReplaceOrderRequest:
    broker_order_id: str
    exchange_code: str
    symbol: str
    replace_quantity: Decimal
    replace_price: Decimal
