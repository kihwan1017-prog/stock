"""Smoke exit isolation — focused regression (no live broker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.position.exit_monitor import (
    ManagedPosition,
    PositionExitMonitorService,
)
from stock_platform.position.smoke_exit_isolation import (
    SUPPRESS_EVENT,
    SmokeExitIsolationLease,
    acquire_smoke_exit_isolation,
    get_smoke_exit_isolation_registry,
    is_exit_submission_suppressed_for_smoke,
    metadata_requests_smoke_exit_isolation,
    release_smoke_exit_isolation,
    smoke_exit_isolation,
)


def _live_pos(**overrides) -> ManagedPosition:
    base = dict(
        account_id=0,
        exchange_code="UPBIT",
        symbol="KRW-AAA",
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        current_price=Decimal("120"),
        highest_price=Decimal("120"),
        stop_loss_price=Decimal("90"),
        take_profit_price=Decimal("110"),
        trailing_stop_ratio=None,
        relative_loss_ratio=None,
        broker_code="UPBIT",
        user_broker_account_id=9001,
        owner_user_id=61,
        environment="LIVE",
    )
    base.update(overrides)
    return ManagedPosition(**base)


@pytest.fixture(autouse=True)
def _reset_registry():
    get_smoke_exit_isolation_registry().reset_all_for_tests()
    yield
    get_smoke_exit_isolation_registry().reset_all_for_tests()


def test_isolation_on_suppresses_exit_submission() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    monitor = PositionExitMonitorService(session)
    fake = MagicMock()
    monitor._execution = fake

    acquire_smoke_exit_isolation(
        user_broker_account_id=9001,
        symbol="KRW-AAA",
        reason="TEST_SMOKE",
    )
    with patch(
        "stock_platform.position.exit_monitor_live.has_blocking_live_exit_sell",
        return_value=False,
    ):
        actions = monitor.evaluate_and_exit([_live_pos()])

    assert len(actions) == 1
    assert actions[0].submitted is False
    assert actions[0].reason == "TAKE_PROFIT"
    fake.submit.assert_not_called()


def test_isolation_off_allows_exit_submission() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    monitor = PositionExitMonitorService(session)
    fake = MagicMock()
    fake.submit.return_value = SimpleNamespace(
        allowed=True, order_id=777, reason_code="OK", outbox_id=1
    )
    monitor._execution = fake

    with patch(
        "stock_platform.position.exit_monitor_live.has_blocking_live_exit_sell",
        return_value=False,
    ):
        actions = monitor.evaluate_and_exit([_live_pos()])

    assert actions[0].submitted is True
    assert actions[0].order_id == 777
    fake.submit.assert_called_once()


def test_uba_scoped_isolation_does_not_affect_other_uba() -> None:
    session = MagicMock()
    monitor = PositionExitMonitorService(session)
    fake = MagicMock()
    fake.submit.return_value = SimpleNamespace(
        allowed=True, order_id=88, reason_code="OK", outbox_id=2
    )
    monitor._execution = fake

    acquire_smoke_exit_isolation(user_broker_account_id=9001, symbol="KRW-AAA")
    other = _live_pos(user_broker_account_id=9002, symbol="KRW-AAA")
    with patch(
        "stock_platform.position.exit_monitor_live.has_blocking_live_exit_sell",
        return_value=False,
    ):
        actions = monitor.evaluate_and_exit([other])

    assert actions[0].submitted is True
    fake.submit.assert_called_once()


def test_context_manager_restores_on_exception() -> None:
    with pytest.raises(RuntimeError):
        with smoke_exit_isolation(
            user_broker_account_id=9001,
            symbol="KRW-AAA",
            reason="CTX",
        ):
            assert (
                is_exit_submission_suppressed_for_smoke(
                    user_broker_account_id=9001, symbol="KRW-AAA"
                )
                is not None
            )
            raise RuntimeError("boom")

    assert (
        is_exit_submission_suppressed_for_smoke(
            user_broker_account_id=9001, symbol="KRW-AAA"
        )
        is None
    )


def test_release_restores_normal_exit_monitoring() -> None:
    lease = acquire_smoke_exit_isolation(
        user_broker_account_id=9001, symbol="KRW-BBB"
    )
    assert release_smoke_exit_isolation(lease.lease_id) is True
    assert (
        is_exit_submission_suppressed_for_smoke(
            user_broker_account_id=9001, symbol="KRW-BBB"
        )
        is None
    )


def test_ttl_expiry_clears_suppression() -> None:
    registry = get_smoke_exit_isolation_registry()
    now = datetime.now(timezone.utc)
    expired = SmokeExitIsolationLease(
        lease_id="expired-lease",
        user_broker_account_id=9001,
        symbol="KRW-CCC",
        reason="TTL",
        correlation_id=None,
        acquired_at=now - timedelta(seconds=120),
        expires_at=now - timedelta(seconds=60),
    )
    with registry._lock:
        registry._leases[expired.lease_id] = expired
    assert (
        is_exit_submission_suppressed_for_smoke(
            user_broker_account_id=9001, symbol="KRW-CCC"
        )
        is None
    )


def test_metadata_smoke_reason_requests_isolation() -> None:
    assert metadata_requests_smoke_exit_isolation(
        {"reason": "UPBIT_UBA_E2E_SMOKE"}
    )
    assert metadata_requests_smoke_exit_isolation(
        {"smoke_exit_isolation": True}
    )
    assert not metadata_requests_smoke_exit_isolation({"reason": "NORMAL"})


def test_suppress_event_constant() -> None:
    assert SUPPRESS_EVENT == "EXIT_TRIGGER_DETECTED_BUT_SUPPRESSED_FOR_SMOKE"
