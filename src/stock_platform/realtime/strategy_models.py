from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class RealtimeSignalAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class RealtimeStrategyConfig:
    short_window: int = 5
    long_window: int = 20
    minimum_change_rate: Decimal = Decimal("0")
    stop_loss_ratio: Decimal = Decimal("0.03")
    take_profit_ratio: Decimal = Decimal("0.06")
    cooldown_seconds: int = 30


@dataclass(frozen=True, slots=True)
class RealtimePositionState:
    quantity: Decimal
    average_entry_price: Decimal | None


@dataclass(frozen=True, slots=True)
class RealtimeSignal:
    exchange_code: str
    symbol: str
    action: RealtimeSignalAction
    signal_price: Decimal
    short_average: Decimal | None
    long_average: Decimal | None
    change_rate: Decimal | None
    reason_code: str
    generated_at: datetime
