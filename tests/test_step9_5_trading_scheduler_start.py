"""STEP 9-5 — Trading Scheduler Start Only 계약 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.realtime.session_models import TradingSessionPhase
from stock_platform.realtime.session_service import (
    RealtimeTradingSessionService,
)
from stock_platform.trading.trading_scheduler_control import (
    get_trading_scheduler_desired_state,
    reset_trading_scheduler_control_for_tests,
    set_trading_scheduler_desired_state,
)
from stock_platform.trading.trading_scheduler_control_service import (
    TradingSchedulerControlError,
    TradingSchedulerControlService,
)


@pytest.fixture(autouse=True)
def _reset_control():
    reset_trading_scheduler_control_for_tests()
    yield
    reset_trading_scheduler_control_for_tests()


def test_desired_state_defaults_pause() -> None:
    assert get_trading_scheduler_desired_state() == "PAUSE"


def test_set_desired_run_and_pause() -> None:
    set_trading_scheduler_desired_state("RUN", actor="a", reason="r")
    assert get_trading_scheduler_desired_state() == "RUN"
    set_trading_scheduler_desired_state("PAUSE", actor="a", reason="p")
    assert get_trading_scheduler_desired_state() == "PAUSE"


@pytest.mark.asyncio
async def test_market_open_does_not_auto_start_runners() -> None:
    session = MagicMock()
    cal = MagicMock()
    cal.evaluate.return_value = SimpleNamespace(
        is_trading_day=True,
        live_allowed=True,
        reason_code="OK",
    )
    with (
        patch(
            "stock_platform.realtime.session_service.TradingCalendarService",
            return_value=cal,
        ),
        patch(
            "stock_platform.realtime.session_service.realtime_execution_runner"
        ) as ex,
        patch(
            "stock_platform.realtime.session_service.realtime_strategy_runner"
        ) as st,
    ):
        ex.status.return_value = {"running": False}
        st.status.return_value = {"running": False}
        # TradingCalendarService is constructed with repo — patch repository path instead
        svc = RealtimeTradingSessionService.__new__(
            RealtimeTradingSessionService
        )
        svc._calendar = cal
        result = await svc.execute(
            phase=TradingSessionPhase.MARKET_OPEN, exchange_code="KRX"
        )
    assert result.executed is True
    assert "explicit start" in result.message
    ex.start.assert_not_called()
    st.start.assert_not_called()


def test_start_requires_reason() -> None:
    session = MagicMock()
    with pytest.raises(TradingSchedulerControlError) as ei:
        TradingSchedulerControlService(session).start(
            actor="admin",
            reason="",
            correlation_id="c1",
            user_broker_account_id=58,
            enforce_gates=False,
        )
    assert ei.value.code == "reason_required"


def test_start_requires_correlation() -> None:
    session = MagicMock()
    with pytest.raises(TradingSchedulerControlError) as ei:
        TradingSchedulerControlService(session).start(
            actor="admin",
            reason="R",
            correlation_id="",
            user_broker_account_id=58,
            enforce_gates=False,
        )
    assert ei.value.code == "correlation_id_required"


def test_start_blocks_live_off() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        is_active=True,
        live_order_enabled=False,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        user_id=7,
        broker_code="UPBIT",
    )
    session.get.return_value = uba
    with pytest.raises(TradingSchedulerControlError) as ei:
        TradingSchedulerControlService(session).assert_start_preconditions(
            user_broker_account_id=58
        )
    assert ei.value.code == "live_required"


def test_start_blocks_arm_off() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        is_active=True,
        live_order_enabled=True,
        live_armed=False,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        user_id=7,
        broker_code="UPBIT",
    )
    session.get.return_value = uba
    with pytest.raises(TradingSchedulerControlError) as ei:
        TradingSchedulerControlService(session).assert_start_preconditions(
            user_broker_account_id=58
        )
    assert ei.value.code == "arm_required"


def test_start_blocks_arm_ttl_insufficient() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        user_id=7,
        broker_code="UPBIT",
    )
    session.get.return_value = uba
    with pytest.raises(TradingSchedulerControlError) as ei:
        TradingSchedulerControlService(session).assert_start_preconditions(
            user_broker_account_id=58, min_arm_remaining_seconds=120
        )
    assert ei.value.code == "arm_ttl_insufficient"


def test_start_idempotent_already_running() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_strategy_runner"
        ) as st,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_execution_runner"
        ) as ex,
    ):
        sched.scheduler.running = True
        sched.scheduler.get_jobs.return_value = []
        st.status.return_value = {"running": False}
        ex.status.return_value = {"running": False}
        result = TradingSchedulerControlService(session).start(
            actor="admin",
            reason="AGAIN",
            correlation_id="dup",
            user_broker_account_id=58,
            enforce_gates=False,
        )
    assert result["already_running"] is True
    assert result["scheduler_changed"] is False


def test_pause_requires_reason() -> None:
    session = MagicMock()
    with pytest.raises(TradingSchedulerControlError) as ei:
        TradingSchedulerControlService(session).pause(
            actor="admin",
            reason="",
            correlation_id="c",
        )
    assert ei.value.code == "reason_required"


def test_collect_readiness_uses_desired_control() -> None:
    from stock_platform.trading.upbit_scheduler_readiness import (
        collect_scheduler_readiness,
    )

    set_trading_scheduler_desired_state("RUN", actor="t", reason="t")
    with patch(
        "stock_platform.realtime.session_runtime.realtime_trading_scheduler"
    ) as sched:
        sched.scheduler.running = True
        snap = collect_scheduler_readiness()
    assert snap.trading_scheduler_desired_state == "RUN"
    assert snap.trading_scheduler_actual_state == "RUNNING"
