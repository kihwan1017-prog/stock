from __future__ import annotations

from datetime import time
from decimal import Decimal

from stock_platform.common.settings import get_settings
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.execution_runner_manager import (
    CompatibilityRealtimeExecutionRunner,
    RealtimeExecutionRunnerManager,
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

# import 시 get_settings() 호출 금지.
# 기본 account_id=1 (Settings.realtime_paper_account_id 기본과 동일).
# 기동 시 apply_realtime_paper_account_from_settings() 로 env 반영.
# LIVE Runner는 Manager가 (uba, broker)별로 따로 만든다. 자동 START 없음.
realtime_execution_runner_manager = RealtimeExecutionRunnerManager(
    signal_bus=realtime_signal_bus,
    safety_guard_template=realtime_safety_guard,
    paper_config=RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.PAPER,
        account_id=1,
        order_amount=Decimal("100000"),
        auto_fill=True,
        allow_buy=True,
        allow_sell=True,
    ),
)
realtime_execution_runner = CompatibilityRealtimeExecutionRunner(
    realtime_execution_runner_manager
)


def apply_realtime_paper_account_from_settings() -> int:
    """Settings 의 REALTIME_PAPER_ACCOUNT_ID 를 runner config 에 반영."""

    account_id = get_settings().realtime_paper_account_id
    current = realtime_execution_runner_manager.paper_runner._config
    realtime_execution_runner_manager.apply_paper_config(
        RealtimeExecutionConfig(
            mode=current.mode,
            account_id=account_id,
            order_amount=current.order_amount,
            auto_fill=current.auto_fill,
            allow_buy=current.allow_buy,
            allow_sell=current.allow_sell,
            user_id=current.user_id,
            user_broker_account_id=current.user_broker_account_id,
            broker_code=current.broker_code,
        )
    )
    return account_id
