from __future__ import annotations

from datetime import time
from decimal import Decimal

from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.execution_runner import (
    RealtimeExecutionRunner,
)
from stock_platform.realtime.manager import (
    realtime_manager,
)
from stock_platform.realtime.safety_guard import (
    RealtimeOrderSafetyGuard,
)
from stock_platform.realtime.safety_models import (
    RealtimeOrderSafetyConfig,
)
from stock_platform.realtime.signal_bus import (
    RealtimeSignalBus,
)
from stock_platform.realtime.strategy_runner import (
    RealtimeStrategyRunner,
)


realtime_signal_bus = RealtimeSignalBus()

realtime_strategy_runner = RealtimeStrategyRunner(
    quote_bus=realtime_manager.bus,
    signal_bus=realtime_signal_bus,
)

realtime_safety_guard = RealtimeOrderSafetyGuard(
    RealtimeOrderSafetyConfig(
        max_order_amount=Decimal("100000"),
        max_daily_loss=Decimal("300000"),
        max_open_positions=5,
        duplicate_order_window_seconds=30,
        symbol_cooldown_seconds=60,
        max_orders_per_minute=10,
        trading_start_time=time(9, 0),
        trading_end_time=time(15, 20),
        enforce_market_hours_for_krx=True,
        live_trading_enabled=False,
        live_unlock_token="",
    )
)

realtime_execution_runner = RealtimeExecutionRunner(
    signal_bus=realtime_signal_bus,
    config=RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.PAPER,
        account_id=1,
        order_amount=Decimal("100000"),
        auto_fill=True,
        allow_buy=True,
        allow_sell=True,
    ),
    safety_guard=realtime_safety_guard,
)
