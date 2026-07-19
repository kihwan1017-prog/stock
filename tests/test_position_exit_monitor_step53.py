"""STEP53 — Position Exit Monitor lifecycle + exit conditions."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.notification.publisher import (
    NotificationPublisher,
)
from stock_platform.position.exit_monitor import (
    ManagedPosition,
    PositionExitMonitorService,
)
from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import ExitEvaluationRequest


def _position(**overrides) -> ManagedPosition:
    base = dict(
        account_id=1,
        exchange_code="KRX",
        symbol="005930",
        quantity=Decimal("2"),
        entry_price=Decimal("70000"),
        current_price=Decimal("70000"),
        highest_price=Decimal("72000"),
        stop_loss_price=Decimal("66500"),
        take_profit_price=Decimal("77000"),
        trailing_stop_ratio=Decimal("0.03"),
        relative_loss_ratio=Decimal("0.08"),
    )
    base.update(overrides)
    return ManagedPosition(**base)


def _monitor_with_execution(
    *,
    allowed: bool = True,
    order_id: int = 42,
    publisher: NotificationPublisher | None = None,
) -> tuple[PositionExitMonitorService, MagicMock]:
    monitor = PositionExitMonitorService.__new__(
        PositionExitMonitorService
    )
    monitor._risk_engine = RiskManagementEngine()
    fake_execution = MagicMock()
    fake_execution.submit.return_value = SimpleNamespace(
        allowed=allowed,
        order_id=order_id if allowed else None,
        reason_code="OK" if allowed else "BLOCKED",
    )
    monitor._execution = fake_execution
    monitor._publisher = publisher or NotificationPublisher()
    return monitor, fake_execution


def test_stop_loss_exit_and_notification() -> None:
    publisher = NotificationPublisher()
    monitor, execution = _monitor_with_execution(
        publisher=publisher
    )
    actions = monitor.evaluate_and_exit(
        [
            _position(
                current_price=Decimal("66000"),
                stop_loss_price=Decimal("66500"),
            )
        ],
        skip_risk_checks=True,
    )
    assert actions[0].submitted is True
    assert actions[0].reason == "STOP_LOSS"
    execution.submit.assert_called_once()
    events = publisher.recent_events()
    assert events[-1].event_type == "STOP_LOSS"


def test_take_profit_exit() -> None:
    monitor, _ = _monitor_with_execution()
    actions = monitor.evaluate_and_exit(
        [
            _position(
                current_price=Decimal("78000"),
                take_profit_price=Decimal("77000"),
            )
        ],
        skip_risk_checks=True,
    )
    assert actions[0].reason == "TAKE_PROFIT"
    assert actions[0].submitted is True


def test_trailing_stop_exit() -> None:
    monitor, _ = _monitor_with_execution()
    # highest=80000, trail 3% → trigger 77600; current below
    actions = monitor.evaluate_and_exit(
        [
            _position(
                entry_price=Decimal("70000"),
                highest_price=Decimal("80000"),
                current_price=Decimal("77000"),
                stop_loss_price=Decimal("60000"),
                take_profit_price=Decimal("90000"),
                trailing_stop_ratio=Decimal("0.03"),
                relative_loss_ratio=None,
            )
        ],
        skip_risk_checks=True,
    )
    assert actions[0].reason == "TRAILING_STOP"
    assert actions[0].submitted is True


def test_relative_loss_exit() -> None:
    decision = RiskManagementEngine().evaluate_exit(
        ExitEvaluationRequest(
            entry_price=Decimal("100"),
            current_price=Decimal("91"),
            highest_price=Decimal("105"),
            stop_loss_price=Decimal("80"),
            take_profit_price=Decimal("120"),
            relative_loss_ratio=Decimal("0.08"),
        )
    )
    assert decision.should_exit is True
    assert decision.reason == "RELATIVE_LOSS"

    publisher = NotificationPublisher()
    monitor, _ = _monitor_with_execution(publisher=publisher)
    actions = monitor.evaluate_and_exit(
        [
            _position(
                entry_price=Decimal("100"),
                current_price=Decimal("91"),
                highest_price=Decimal("105"),
                stop_loss_price=Decimal("80"),
                take_profit_price=Decimal("120"),
                trailing_stop_ratio=None,
                relative_loss_ratio=Decimal("0.08"),
            )
        ],
        skip_risk_checks=True,
    )
    assert actions[0].reason == "RELATIVE_LOSS"
    assert publisher.recent_events()[-1].event_type == (
        "RELATIVE_LOSS"
    )


def test_kill_switch_force_exit() -> None:
    publisher = NotificationPublisher()
    monitor, execution = _monitor_with_execution(
        publisher=publisher
    )
    actions = monitor.evaluate_and_exit(
        [
            _position(
                force_exit_reason="KILL_SWITCH",
                current_price=Decimal("70000"),
            )
        ],
        skip_risk_checks=True,
    )
    assert actions[0].reason == "KILL_SWITCH"
    assert actions[0].submitted is True
    execution.submit.assert_called_once()
    assert publisher.recent_events()[-1].event_type == (
        "KILL_SWITCH"
    )


def test_daily_loss_force_exit() -> None:
    publisher = NotificationPublisher()
    monitor, _ = _monitor_with_execution(publisher=publisher)
    actions = monitor.evaluate_and_exit(
        [
            _position(
                force_exit_reason="DAILY_LOSS",
            )
        ],
        skip_risk_checks=True,
    )
    assert actions[0].reason == "DAILY_LOSS"
    assert actions[0].submitted is True
    assert publisher.recent_events()[-1].event_type == (
        "DAILY_LOSS"
    )


def test_hold_does_not_submit() -> None:
    monitor, execution = _monitor_with_execution()
    actions = monitor.evaluate_and_exit(
        [_position(current_price=Decimal("71000"))],
        skip_risk_checks=True,
    )
    assert actions[0].reason == "HOLD"
    assert actions[0].submitted is False
    execution.submit.assert_not_called()


def test_exit_order_failure_is_logged_and_reported() -> None:
    publisher = NotificationPublisher()
    monitor, execution = _monitor_with_execution(
        allowed=False,
        publisher=publisher,
    )
    actions = monitor.evaluate_and_exit(
        [
            _position(
                current_price=Decimal("66000"),
                stop_loss_price=Decimal("66500"),
            )
        ],
        skip_risk_checks=True,
    )
    assert actions[0].submitted is False
    assert actions[0].reason == "STOP_LOSS"
    events = publisher.recent_events()
    assert events[-1].detail["submitted"] is False
    assert events[-1].detail["error"] == "BLOCKED"
    execution.submit.assert_called_once()


def test_lifecycle_starts_exit_monitor_scheduler() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from stock_platform.api.lifecycle import (
        ApplicationLifecycle,
    )

    lifecycle = ApplicationLifecycle()

    with patch(
        "stock_platform.api.lifecycle.validate_startup_settings"
    ), patch(
        "stock_platform.api.lifecycle.verify_database_connection",
        new=AsyncMock(),
    ), patch(
        "stock_platform.api.lifecycle.bootstrap_auth_admin",
        new=AsyncMock(),
    ), patch(
        "stock_platform.api.lifecycle.broker_recovery_manager.recover",
        new=AsyncMock(return_value={"success": True}),
    ), patch.object(
        lifecycle,
        "_startup_strategy_runtime",
        new=AsyncMock(),
    ), patch(
        "stock_platform.api.lifecycle.market_data_persistence_worker.start",
        new=AsyncMock(),
    ), patch(
        "stock_platform.api.lifecycle.daily_loss_monitor_scheduler.start"
    ) as daily_start, patch(
        "stock_platform.api.lifecycle.position_exit_monitor_scheduler.start"
    ) as exit_start, patch(
        "stock_platform.api.lifecycle.strategy_runtime_reload_scheduler.start"
    ), patch(
        "stock_platform.api.lifecycle.strategy_approval_scheduler.start"
    ), patch(
        "stock_platform.api.lifecycle.strategy_deployment_pipeline_scheduler.start"
    ), patch(
        "stock_platform.api.lifecycle.deployment_performance_monitor_scheduler.start"
    ), patch(
        "stock_platform.api.lifecycle.order_outbox_scheduler.start"
    ):
        asyncio.run(lifecycle.startup())

    daily_start.assert_called_once()
    exit_start.assert_called_once()
    assert lifecycle.started is True


def test_scheduler_respects_disabled_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "POSITION_EXIT_MONITOR_ENABLED", "false"
    )
    from stock_platform.common.settings import get_settings
    from stock_platform.position.exit_monitor_scheduler import (
        PositionExitMonitorScheduler,
    )

    get_settings.cache_clear()
    try:
        scheduler = PositionExitMonitorScheduler()
        scheduler.start()
        assert scheduler.scheduler.running is False
    finally:
        get_settings.cache_clear()
