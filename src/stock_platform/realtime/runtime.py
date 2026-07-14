from __future__ import annotations

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
)
