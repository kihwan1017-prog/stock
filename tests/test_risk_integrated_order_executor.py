from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
)
from stock_platform.realtime.risk_integrated_order_executor import (
    RiskIntegratedRealtimeOrderExecutor,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)


def test_blocks_when_account_number_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "stock_platform.realtime.risk_integrated_order_executor.get_settings",
        lambda: SimpleNamespace(kiwoom_account_number=""),
    )

    executor = (
        RiskIntegratedRealtimeOrderExecutor.__new__(
            RiskIntegratedRealtimeOrderExecutor
        )
    )
    executor._session = object()
    executor._execution_config = (
        RealtimeExecutionConfig(
            order_amount=Decimal("100000")
        )
    )
    executor._safety_guard = object()

    signal = RealtimeSignal(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        action=RealtimeSignalAction.BUY,
        signal_price=Decimal("100000000"),
        short_average=None,
        long_average=None,
        change_rate=None,
        reason_code="TEST",
        generated_at=datetime.now(timezone.utc),
    )

    result = executor.execute(signal)

    assert result.order_status == "SKIPPED"
    assert result.reason_code == (
        "RISK_ACCOUNT_NUMBER_MISSING"
    )
