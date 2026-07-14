from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
)
from stock_platform.realtime.order_executor import (
    RealtimePaperOrderExecutor,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)


class FakeOrderService:
    def create(self, **kwargs):
        return SimpleNamespace(
            order_id=11,
            status_code="ACCEPTED",
        )


class FakeExecutionService:
    def apply_fill(self, **kwargs):
        return SimpleNamespace(
            trade_id=21,
            order_status="FILLED",
        )


def _signal(
    action: RealtimeSignalAction,
) -> RealtimeSignal:
    return RealtimeSignal(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        action=action,
        signal_price=Decimal("100000000"),
        short_average=Decimal("99000000"),
        long_average=Decimal("98000000"),
        change_rate=Decimal("0.01"),
        reason_code="MA_GOLDEN_CROSS",
        generated_at=datetime.now(timezone.utc),
    )


def test_buy_signal_creates_and_fills_order() -> None:
    executor = RealtimePaperOrderExecutor.__new__(
        RealtimePaperOrderExecutor
    )
    executor._config = RealtimeExecutionConfig(
        account_id=1,
        order_amount=Decimal("100000"),
        auto_fill=True,
    )
    executor._order_service = FakeOrderService()
    executor._execution_service = FakeExecutionService()

    result = executor.execute(
        _signal(RealtimeSignalAction.BUY)
    )

    assert result.order_id == 11
    assert result.trade_id == 21
    assert result.order_status == "FILLED"
    assert result.quantity == Decimal(
        "0.00100000"
    )


def test_hold_signal_is_skipped() -> None:
    executor = RealtimePaperOrderExecutor.__new__(
        RealtimePaperOrderExecutor
    )
    executor._config = RealtimeExecutionConfig(
        account_id=1,
        order_amount=Decimal("100000"),
        auto_fill=True,
    )
    executor._order_service = FakeOrderService()
    executor._execution_service = FakeExecutionService()

    result = executor.execute(
        _signal(RealtimeSignalAction.HOLD)
    )

    assert result.order_status == "SKIPPED"
    assert result.order_id is None
    assert result.reason_code == "HOLD_SIGNAL"
