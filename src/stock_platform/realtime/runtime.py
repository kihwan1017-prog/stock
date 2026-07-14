from __future__ import annotations

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
