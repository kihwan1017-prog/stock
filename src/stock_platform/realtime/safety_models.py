from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RealtimeOrderSafetyConfig:
    max_order_amount: Decimal = Decimal("100000")
    max_daily_loss: Decimal = Decimal("300000")
    max_open_positions: int = 5
    duplicate_order_window_seconds: int = 30
    symbol_cooldown_seconds: int = 60
    max_orders_per_minute: int = 10
    trading_start_time: time = time(9, 0)
    trading_end_time: time = time(15, 20)
    enforce_market_hours_for_krx: bool = True
    live_trading_enabled: bool = False
    live_unlock_token: str = ""


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    allowed: bool
    reason_code: str
    message: str
