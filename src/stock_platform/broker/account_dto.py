from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class BrokerPositionSnapshot:
    exchange_code: str
    symbol: str
    name: str
    quantity: Decimal
    available_quantity: Decimal
    average_purchase_price: Decimal
    current_price: Decimal
    purchase_amount: Decimal
    evaluation_amount: Decimal
    profit_loss: Decimal
    return_rate: Decimal
    raw_data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BrokerAccountSyncResult:
    broker_code: str
    account_number: str
    deposit_amount: Decimal
    available_order_amount: Decimal
    total_purchase_amount: Decimal
    total_evaluation_amount: Decimal
    total_profit_loss: Decimal
    total_return_rate: Decimal
    positions: list[BrokerPositionSnapshot]
    synchronized_at: datetime
    raw_data: dict[str, Any]
