"""Execution stack reconciliation + heartbeat verify tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.trading.execution_stack_reconciliation import (
    evaluate_desired_execution_state,
    execution_stack_needs_restore,
    reconcile_desired_execution_state,
    verify_stack_restored,
)


def _base_snap(*, components: dict[str, str], heartbeats: dict | None = None) -> dict:
    return {
        "health_state": "BROKEN",
        "partial_restore": True,
        "live": "ON",
        "arm": "ON",
        "activation": "ACTIVE",
        "components": components,
        "heartbeats": heartbeats or {},
    }


def test_desired_state_when_live_arm_activation_lease() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.execution_stack_reconciliation.LiveTradingTransitionService"
        ) as act,
        patch(
            "stock_platform.trading.execution_stack_reconciliation.LiveUnattendedAuthorizationService"
        ) as lease_svc,
    ):
        act.return_value.peek_active.return_value = object()
        lease_svc.return_value.get_active.return_value = SimpleNamespace(
            status_code="ACTIVE"
        )
        out = evaluate_desired_execution_state(session, user_broker_account_id=1380)

    assert out["desired_execution_running"] is True
    assert out["components"]["runtime"] == "RUNNING"
    assert out["components"]["feed"] == "RUNNING"


def test_full_stack_down_needs_restore() -> None:
    session = MagicMock()
    snap = _base_snap(
        components={
            "runtime": "STOPPED",
            "runner": "STOPPED",
            "worker": "STOPPED",
            "exit_monitor": "STOPPED",
            "scanner": "STOPPED",
            "feed": "DISCONNECTED",
        }
    )
    with (
        patch(
            "stock_platform.trading.execution_stack_reconciliation.evaluate_desired_execution_state",
            return_value={
                "desired_execution_running": True,
                "broker": "UPBIT",
                "components": {k: "RUNNING" for k in snap["components"]},
            },
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation.build_trading_health_snapshot",
            return_value=snap,
        ),
    ):
        need = execution_stack_needs_restore(session, user_broker_account_id=1380)

    assert need["needs_restore"] is True
    assert need["restore_kind"] == "FULL_EXECUTION_STACK_DOWN"
    assert len(need["down_components"]) == 6


def test_partial_stack_down_needs_restore() -> None:
    session = MagicMock()
    snap = _base_snap(
        components={
            "runtime": "RUNNING",
            "runner": "RUNNING",
            "worker": "STOPPED",
            "exit_monitor": "RUNNING",
            "scanner": "RUNNING",
            "feed": "REAL_FRESH",
        }
    )
    with (
        patch(
            "stock_platform.trading.execution_stack_reconciliation.evaluate_desired_execution_state",
            return_value={"desired_execution_running": True, "broker": "UPBIT"},
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation.build_trading_health_snapshot",
            return_value=snap,
        ),
    ):
        need = execution_stack_needs_restore(session, user_broker_account_id=1380)

    assert need["needs_restore"] is True
    assert need["restore_kind"] == "PARTIAL_RESTORE"
    assert need["down_components"] == ["worker"]


def test_verify_stack_restored_requires_fresh_heartbeats() -> None:
    session = MagicMock()
    snap = _base_snap(
        components={
            "runtime": "RUNNING",
            "runner": "RUNNING",
            "worker": "RUNNING",
            "exit_monitor": "RUNNING",
            "scanner": "RUNNING",
            "feed": "REAL_FRESH",
        },
        heartbeats={
            "runner_heartbeat_age_seconds": 5.0,
            "worker_heartbeat_age_seconds": 5.0,
            "exit_heartbeat_age_seconds": 5.0,
            "feed_age_seconds": 5.0,
        },
    )
    with patch(
        "stock_platform.trading.execution_stack_reconciliation.build_trading_health_snapshot",
        return_value=snap,
    ):
        ok = verify_stack_restored(session, user_broker_account_id=1380)
    assert ok["restore_succeeded"] is True

    snap_stale = {
        **snap,
        "heartbeats": {
            **snap["heartbeats"],
            "runner_heartbeat_age_seconds": 999.0,
        },
    }
    with patch(
        "stock_platform.trading.execution_stack_reconciliation.build_trading_health_snapshot",
        return_value=snap_stale,
    ):
        bad = verify_stack_restored(session, user_broker_account_id=1380)
    assert bad["restore_succeeded"] is False
    assert "runner" in bad["missing_components"]


@pytest.mark.asyncio
async def test_startup_reconcile_all_stopped_triggers_l2() -> None:
    session = MagicMock()
    session.commit = MagicMock()

    need = {
        "needs_restore": True,
        "restore_kind": "FULL_EXECUTION_STACK_DOWN",
        "down_components": ["runtime", "runner", "worker", "exit_monitor", "scanner", "feed"],
        "actual": {
            "runtime": "STOPPED",
            "runner": "STOPPED",
            "worker": "STOPPED",
            "exit_monitor": "STOPPED",
            "scanner": "STOPPED",
            "feed": "DISCONNECTED",
        },
        "desired": {"broker": "UPBIT", "desired_execution_running": True},
    }
    verify_ok = {"restore_succeeded": True, "verified": {}, "missing_components": []}

    import stock_platform.trading.autotrading_reliability_watchdog as wd_mod

    with (
        patch(
            "stock_platform.trading.execution_stack_reconciliation.execution_stack_needs_restore",
            return_value=need,
        ),
        patch.object(
            wd_mod, "_l1_feed_reconnect", new_callable=AsyncMock, return_value={"ok": True}
        ),
        patch.object(wd_mod, "_l1_scanner_restore", return_value={"started": True}),
        patch(
            "stock_platform.trading.upbit_unattended_stack_restore.restore_upbit_trading_stack",
            new_callable=AsyncMock,
            return_value={"restored": True, "detail": {}},
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation.verify_stack_restored",
            side_effect=[verify_ok],
        ),
    ):
        out = await reconcile_desired_execution_state(
            session, user_broker_account_id=1380, actor="TEST"
        )

    assert out["restore_attempted"] is True
    assert "L2_STACK" in out["actions"]
    assert out["restore_succeeded"] is True


@pytest.mark.asyncio
async def test_reconcile_failure_not_success_on_flag_only() -> None:
    session = MagicMock()
    need = {
        "needs_restore": True,
        "restore_kind": "PARTIAL_RESTORE",
        "down_components": ["worker"],
        "actual": {"worker": "STOPPED", "feed": "REAL_FRESH", "scanner": "RUNNING"},
        "desired": {"broker": "UPBIT", "desired_execution_running": True},
    }
    verify_fail = {
        "restore_succeeded": False,
        "missing_components": ["worker"],
        "verified": {"worker": False},
    }

    with (
        patch(
            "stock_platform.trading.execution_stack_reconciliation.execution_stack_needs_restore",
            return_value=need,
        ),
        patch(
            "stock_platform.trading.upbit_unattended_stack_restore.restore_upbit_trading_stack",
            new_callable=AsyncMock,
            return_value={"restored": True, "detail": {"stack_ok": True}},
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation.verify_stack_restored",
            return_value=verify_fail,
        ),
    ):
        out = await reconcile_desired_execution_state(
            session, user_broker_account_id=1380, actor="TEST"
        )

    assert out["restore_succeeded"] is False
    assert out["missing_components"] == ["worker"]
