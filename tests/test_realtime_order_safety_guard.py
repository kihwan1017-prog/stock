from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.realtime.execution_models import (
    RealtimeExecutionMode,
)
from stock_platform.realtime.safety_guard import (
    RealtimeOrderSafetyGuard,
)
from stock_platform.realtime.safety_models import (
    RealtimeOrderSafetyConfig,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)


def _signal(
    action=RealtimeSignalAction.BUY,
) -> RealtimeSignal:
    return RealtimeSignal(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        action=action,
        signal_price=Decimal("100000000"),
        short_average=None,
        long_average=None,
        change_rate=Decimal("0.01"),
        reason_code="MA_GOLDEN_CROSS",
        generated_at=datetime.now(timezone.utc),
    )


def test_blocks_order_amount_over_limit() -> None:
    guard = RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            max_order_amount=Decimal("100000")
        )
    )

    decision = guard.evaluate(
        signal=_signal(),
        mode=RealtimeExecutionMode.PAPER,
        order_amount=Decimal("200000"),
        open_position_count=0,
    )

    assert decision.allowed is False
    assert decision.reason_code == (
        "MAX_ORDER_AMOUNT_EXCEEDED"
    )


def test_blocks_duplicate_signal() -> None:
    guard = RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            symbol_cooldown_seconds=0,
            duplicate_order_window_seconds=60,
        )
    )
    signal = _signal()

    first = guard.evaluate(
        signal=signal,
        mode=RealtimeExecutionMode.PAPER,
        order_amount=Decimal("100000"),
        open_position_count=0,
    )
    assert first.allowed is True

    guard.mark_order_executed(signal)

    second = guard.evaluate(
        signal=signal,
        mode=RealtimeExecutionMode.PAPER,
        order_amount=Decimal("100000"),
        open_position_count=0,
    )

    assert second.allowed is False
    assert second.reason_code == (
        "DUPLICATE_ORDER_BLOCKED"
    )


def test_live_mode_is_locked_by_default() -> None:
    guard = RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            live_trading_enabled=False
        )
    )

    decision = guard.evaluate(
        signal=_signal(),
        mode=RealtimeExecutionMode.LIVE,
        order_amount=Decimal("100000"),
        open_position_count=0,
    )

    assert decision.allowed is False
    assert decision.reason_code == (
        "LIVE_TRADING_DISABLED"
    )


def test_daily_loss_limit() -> None:
    guard = RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            max_daily_loss=Decimal("100000")
        )
    )

    guard.add_realized_profit_loss(
        Decimal("-120000")
    )

    decision = guard.evaluate(
        signal=_signal(),
        mode=RealtimeExecutionMode.PAPER,
        order_amount=Decimal("100000"),
        open_position_count=0,
    )

    assert decision.allowed is False
    assert decision.reason_code == (
        "DAILY_LOSS_LIMIT_REACHED"
    )
