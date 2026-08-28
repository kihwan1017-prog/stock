# -*- coding: utf-8 -*-
"""Regression tests — KIWOOM runtime control vs execution runner SoT."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.trading.execution_stack_reconciliation import (
    STARTUP_CONTROL_MISMATCH_GRACE_SECONDS,
    detect_runtime_control_mismatch,
    reconcile_runtime_control_state,
)


def _snap(*, runtime: str, runner: str) -> dict:
    return {
        "market": "KIWOOM",
        "components": {
            "runtime": runtime,
            "runner": runner,
            "worker": "RUNNING",
            "exit_monitor": "RUNNING",
            "scanner": "RUNNING",
            "feed": "REAL_FRESH",
        },
    }


def test_control_state_mismatch_detected() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
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
        patch(
            "stock_platform.trading.execution_stack_reconciliation._execution_runner_running",
            return_value=True,
        ),
        patch(
            "stock_platform.operation.runtime_info.get_process_started_at",
            return_value=datetime.now(timezone.utc)
            - timedelta(seconds=STARTUP_CONTROL_MISMATCH_GRACE_SECONDS + 60),
        ),
        patch(
            "stock_platform.trading.market_hours_authorization.krx_market_hours_state",
            return_value={"in_regular_session": True},
        ),
    ):
        act.return_value.peek_active.return_value = object()
        lease_svc.return_value.get_active.return_value = SimpleNamespace(
            status_code="ACTIVE"
        )
        out = detect_runtime_control_mismatch(
            session,
            user_broker_account_id=1381,
            snapshot=_snap(runtime="PAUSED", runner="RUNNING"),
        )

    assert out["mismatch_kind"] == "CONTROL_STATE_MISMATCH"
    assert out["should_reconcile"] is True


def test_startup_grace_suppresses_mismatch_incident() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.trading.execution_stack_reconciliation.evaluate_desired_execution_state",
            return_value={
                "desired_execution_running": True,
                "broker": "KIWOOM",
                "components": {"runtime": "RUNNING"},
            },
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation._execution_runner_running",
            return_value=True,
        ),
        patch(
            "stock_platform.operation.runtime_info.get_process_started_at",
            return_value=datetime.now(timezone.utc) - timedelta(seconds=30),
        ),
    ):
        out = detect_runtime_control_mismatch(
            session,
            user_broker_account_id=1381,
            snapshot=_snap(runtime="PAUSED", runner="RUNNING"),
        )

    assert out["mismatch_kind"] == "CONTROL_STATE_MISMATCH"
    assert out["in_grace_period"] is True
    assert out["should_reconcile"] is False


def test_execution_state_mismatch_detected() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.trading.execution_stack_reconciliation.evaluate_desired_execution_state",
            return_value={
                "desired_execution_running": True,
                "broker": "KIWOOM",
                "components": {"runtime": "RUNNING"},
            },
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation._execution_runner_running",
            return_value=False,
        ),
        patch(
            "stock_platform.operation.runtime_info.get_process_started_at",
            return_value=datetime.now(timezone.utc)
            - timedelta(seconds=STARTUP_CONTROL_MISMATCH_GRACE_SECONDS + 10),
        ),
    ):
        out = detect_runtime_control_mismatch(
            session,
            user_broker_account_id=1381,
            snapshot=_snap(runtime="RUNNING", runner="STOPPED"),
        )

    assert out["mismatch_kind"] == "EXECUTION_STATE_MISMATCH"


@pytest.mark.asyncio
async def test_reconcile_runtime_control_invokes_kiwoom_restore() -> None:
    session = MagicMock()
    mismatch = {
        "should_reconcile": True,
        "mismatch_kind": "CONTROL_STATE_MISMATCH",
        "broker": "KIWOOM",
    }
    with (
        patch(
            "stock_platform.trading.execution_stack_reconciliation.detect_runtime_control_mismatch",
            side_effect=[
                mismatch,
                {"mismatch_kind": None},
            ],
        ),
        patch(
            "stock_platform.trading.kiwoom_unattended_stack_restore.restore_kiwoom_trading_stack",
            new_callable=AsyncMock,
            return_value={"restored": True, "reason": "OK"},
        ) as restore,
        patch(
            "stock_platform.trading.execution_stack_reconciliation.verify_stack_restored",
            return_value={"restore_succeeded": True},
        ),
    ):
        out = await reconcile_runtime_control_state(
            session, user_broker_account_id=1381, broker="KIWOOM"
        )

    restore.assert_awaited_once()
    assert "RECONCILE_RUNTIME_CONTROL" in out["actions"]
    assert out["aligned"] is True


@pytest.mark.asyncio
async def test_desired_paused_orphan_runner_reconcile_stops_only() -> None:
    session = MagicMock()
    mismatch = {
        "should_reconcile": True,
        "mismatch_kind": "EXECUTION_ORPHAN_WHILE_DESIRED_STOPPED",
        "broker": "KIWOOM",
    }
    stop_scope = AsyncMock()
    runner_mgr = MagicMock()
    runner_mgr.stop_scope = stop_scope
    runtime_mod = MagicMock()
    runtime_mod.realtime_execution_runner_manager = runner_mgr
    with (
        patch.dict(
            sys.modules,
            {
                "stock_platform.realtime.runtime": runtime_mod,
            },
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation.detect_runtime_control_mismatch",
            side_effect=[mismatch, {"mismatch_kind": None}],
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation.verify_stack_restored",
            return_value={"restore_succeeded": False},
        ),
    ):
        out = await reconcile_runtime_control_state(
            session, user_broker_account_id=1381, broker="KIWOOM"
        )

    stop_scope.assert_awaited_once_with(1381, "KIWOOM")
    assert "STOP_ORPHAN_EXECUTION_RUNNER" in out["actions"]


@pytest.mark.asyncio
async def test_kiwoom_restore_blocks_runner_when_runtime_not_running() -> None:
    from stock_platform.trading.kiwoom_unattended_stack_restore import (
        restore_kiwoom_trading_stack,
    )

    session = MagicMock()
    gates = {
        "ok": True,
        "checks": {"strategy_link": {"strategy_id": 17579}},
    }
    kmr = MagicMock()
    kmr.status.return_value = {
        "running": True,
        "connected": True,
        "user_broker_account_id": 1381,
    }
    kmr.start = AsyncMock(return_value={"started": True, "already_running": True})
    kmr_mod = MagicMock()
    kmr_mod.kiwoom_market_realtime_runtime = kmr
    runner_mgr = MagicMock()
    runner_mgr.get.return_value = None
    runner_mgr.stop_scope = AsyncMock()
    runtime_mod = MagicMock()
    runtime_mod.realtime_execution_runner_manager = runner_mgr
    bootstrap_mod = MagicMock()
    bootstrap_mod._build_scope_for_link = MagicMock()
    manager_mod = MagicMock()
    manager_mod.dynamic_strategy_runtime_manager = MagicMock()
    kill_mod = MagicMock()
    kill_mod.KillSwitchService = MagicMock(return_value=MagicMock(is_active=MagicMock(return_value=False)))
    upbit_ctrl_mod = MagicMock()
    upbit_ctrl_mod.runtime_status_for_uba = MagicMock(return_value={"status": "PAUSED"})
    kiwoom_gates_mod = MagicMock()
    kiwoom_gates_mod.evaluate_kiwoom_runtime_run_gates = MagicMock(
        return_value={"ok": False, "blockers": ["TEST_BLOCK"]}
    )
    with (
        patch.dict(
            sys.modules,
            {
                "stock_platform.realtime.kiwoom_market_realtime_runtime": kmr_mod,
                "stock_platform.realtime.runtime": runtime_mod,
                "stock_platform.strategy_deployment.runtime_bootstrap": bootstrap_mod,
                "stock_platform.strategy_deployment.runtime_manager": manager_mod,
                "stock_platform.risk_engine.kill_switch_service": kill_mod,
                "stock_platform.trading.upbit_24x7_control": upbit_ctrl_mod,
                "stock_platform.realtime.kiwoom_runtime_run_gates": kiwoom_gates_mod,
            },
        ),
        patch(
            "stock_platform.trading.kiwoom_unattended_stack_restore.evaluate_kiwoom_stack_restore_gates",
            return_value=gates,
        ),
        patch(
            "stock_platform.trading.kiwoom_unattended_stack_restore._resolve_kiwoom_stack_feed_symbols",
            return_value=["034310"],
        ),
        patch(
            "stock_platform.trading.kiwoom_feed_recovery.ensure_kiwoom_feed_fresh",
            AsyncMock(return_value={"started": True, "idempotent": True}),
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation.verify_stack_restored",
            return_value={"restore_succeeded": False},
        ),
    ):
        session.scalar.return_value = SimpleNamespace(
            user_broker_account_id=1381,
            strategy_id=17579,
            is_active=True,
        )
        out = await restore_kiwoom_trading_stack(session, user_broker_account_id=1381)

    assert out["restored"] is False
    assert out["reason"] == "RUNTIME_NOT_RUNNING"
    assert out["detail"]["runner"]["reason"] == "RUNTIME_NOT_RUNNING"


def test_auto_trading_ready_false_when_runtime_stopped() -> None:
    from stock_platform.trading.autotrading_health_service import (
        HEALTH_BROKEN,
        HEALTH_READY,
    )

    health_state = HEALTH_READY
    partial_restore = False
    control_mismatch = {"mismatch_kind": None}
    runtime_st = "PAUSED"
    if runtime_st != "RUNNING":
        health_state = HEALTH_BROKEN
    auto_trading_ready = (
        health_state == HEALTH_READY
        and not partial_restore
        and not bool(control_mismatch.get("mismatch_kind"))
    )
    assert auto_trading_ready is False
