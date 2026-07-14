from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class RealtimeExecutionMode(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"


@dataclass(frozen=True, slots=True)
class RealtimeExecutionConfig:
    mode: RealtimeExecutionMode = RealtimeExecutionMode.PAPER
    account_id: int = 1
    order_amount: Decimal = Decimal("100000")
    auto_fill: bool = True
    allow_buy: bool = True
    allow_sell: bool = True


@dataclass(frozen=True, slots=True)
class RealtimeExecutionResult:
    exchange_code: str
    symbol: str
    signal_action: str
    execution_mode: str
    order_id: int | None
    trade_id: int | None
    order_status: str
    quantity: Decimal
    order_price: Decimal
    reason_code: str
    executed_at: datetime
