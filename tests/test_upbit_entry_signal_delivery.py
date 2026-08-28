"""Entry signal delivery — executor session commit + publish outcome."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
    RealtimeExecutionResult,
)
from stock_platform.realtime.execution_runner import RealtimeExecutionRunner
from stock_platform.realtime.safety_guard import RealtimeOrderSafetyGuard
from stock_platform.realtime.safety_models import RealtimeOrderSafetyConfig
from stock_platform.realtime.signal_bus import RealtimeSignalBus
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)
from stock_platform.realtime.strategy_signal import StrategySignal
from stock_platform.realtime.scoped_signal_pipeline import (
    publish_scoped_signal,
    reset_signal_dedup_for_tests,
)


def _guard() -> RealtimeOrderSafetyGuard:
    return RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            max_order_amount=Decimal("100000"),
            max_daily_loss=Decimal("300000"),
            max_open_positions=5,
            live_trading_enabled=False,
        )
    )


def test_execute_signal_commits_session_after_skip() -> None:
    """SKIP 경로에서도 executor session commit — EXECUTOR_* trace 유실 방지."""

    bus = RealtimeSignalBus()
    runner = RealtimeExecutionRunner(
        signal_bus=bus,
        config=RealtimeExecutionConfig(
            mode=RealtimeExecutionMode.LIVE,
            account_id=1,
            order_amount=Decimal("100000"),
            user_broker_account_id=1380,
            broker_code="UPBIT",
        ),
        safety_guard=_guard(),
    )
    session = MagicMock()
    skipped = RealtimeExecutionResult(
        exchange_code="UPBIT",
        symbol="KRW-LINK",
        signal_action="BUY",
        execution_mode="LIVE",
        order_id=None,
        trade_id=None,
        order_status="SKIPPED",
        quantity=Decimal("0"),
        order_price=Decimal("1"),
        reason_code="TEST_SKIP",
        executed_at=datetime.now(timezone.utc),
    )
    signal = RealtimeSignal(
        exchange_code="UPBIT",
        symbol="KRW-LINK",
        action=RealtimeSignalAction.BUY,
        signal_price=Decimal("10"),
        short_average=None,
        long_average=None,
        change_rate=None,
        reason_code="PORTFOLIO_BULLISH_STATE_ENTRY",
        generated_at=datetime.now(timezone.utc),
        execution_trace_id=str(uuid4()),
        account_kind="USER_BROKER",
        account_id=1380,
        user_broker_account_id=1380,
        broker_code="UPBIT",
    )

    with (
        patch(
            "stock_platform.realtime.execution_runner.get_session_factory",
            return_value=lambda: session,
        ),
        patch(
            "stock_platform.realtime.execution_runner.RiskIntegratedRealtimeOrderExecutor"
        ) as exec_cls,
    ):
        exec_cls.return_value.execute.return_value = skipped
        out = runner._execute_signal(signal)

    assert out.order_status == "SKIPPED"
    session.commit.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.asyncio
async def test_publish_scoped_signal_writes_published_trace() -> None:
    reset_signal_dedup_for_tests()
    signal = StrategySignal(
        signal_id="sig_pub_test",
        fingerprint=f"fp_{uuid4().hex[:16]}",
        scope_key="user:1|uba:1380|sid:1|ver:t|type:CRYPTO|broker:UPBIT",
        user_id=1,
        account_kind="USER_BROKER",
        account_id=1380,
        strategy_id=1,
        strategy_version="t",
        broker_code="UPBIT",
        market_type="CRYPTO",
        symbol="KRW-LINK",
        signal_type="BUY",
        generated_at=datetime.now(timezone.utc),
        event_time=datetime.now(timezone.utc),
        reference_price=Decimal("1"),
        reason_code="PORTFOLIO_BULLISH_STATE_ENTRY",
        metadata={
            "execution_trace_id": str(uuid4()),
            "selection_id": 282,
            "candidate_selection_id": 282,
            "lifecycle_kind": "INITIAL",
        },
    )
    with (
        patch(
            "stock_platform.realtime.scoped_signal_pipeline._guards_allow",
            return_value=True,
        ),
        patch(
            "stock_platform.realtime.runtime.realtime_signal_bus"
        ) as bus,
        patch(
            "stock_platform.realtime.scoped_signal_pipeline._trace_publish_outcome"
        ) as trace,
    ):
        bus.publish = MagicMock()
        # publish is async
        async def _pub(_s):
            return None

        bus.publish = _pub
        out = await publish_scoped_signal(signal)
    assert out["published"] is True
    trace.assert_called_once()
    assert trace.call_args.args[1]["published"] is True
