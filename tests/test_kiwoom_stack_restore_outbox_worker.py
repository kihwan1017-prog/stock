"""Kiwoom stack restore — outbox worker unattended start."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.trading.kiwoom_unattended_stack_restore import (
    restore_kiwoom_trading_stack,
)


@pytest.mark.asyncio
async def test_kiwoom_stack_restore_starts_outbox_worker_when_stopped() -> None:
    session = MagicMock()
    link = MagicMock()
    session.scalar = MagicMock(return_value=link)

    with (
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime"
        ) as worker_rt,
        patch(
            "stock_platform.trading.kiwoom_unattended_stack_restore.evaluate_kiwoom_stack_restore_gates",
            return_value={
                "ok": True,
                "blockers": [],
                "checks": {"strategy_link": {"strategy_id": 17579}},
            },
        ),
        patch(
            "stock_platform.trading.kiwoom_unattended_stack_restore._resolve_kiwoom_stack_feed_symbols",
            return_value=["034310"],
        ),
        patch(
            "stock_platform.trading.kiwoom_feed_recovery.ensure_kiwoom_feed_running",
            new_callable=AsyncMock,
            return_value={"started": True, "already_running": True},
        ),
        patch(
            "stock_platform.realtime.kiwoom_runtime_run_gates.evaluate_kiwoom_runtime_run_gates",
            return_value={"ok": True, "blockers": []},
        ),
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
        ) as kill_cls,
        patch(
            "stock_platform.strategy_deployment.runtime_bootstrap._build_scope_for_link",
            return_value=(MagicMock(scope_key="k"), None),
        ),
        patch(
            "stock_platform.strategy_deployment.runtime_manager.dynamic_strategy_runtime_manager"
        ) as rt_mgr,
        patch(
            "stock_platform.trading.upbit_24x7_control.runtime_status_for_uba",
            return_value={"status": "RUNNING"},
        ),
        patch(
            "stock_platform.realtime.runtime.realtime_execution_runner_manager"
        ) as runner_mgr,
        patch(
            "stock_platform.api.v1.realtime_execution._start_live_for_uba",
            new_callable=AsyncMock,
            return_value={"started": True, "user_broker_account_id": 1381},
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation.verify_stack_restored",
            return_value={"restore_succeeded": True, "core_restored": True},
        ),
    ):
        worker_rt.status.return_value = {"enabled": True, "running": False}
        worker_rt.start.return_value = {"started": True, "reason": "STARTED"}

        from stock_platform.strategy_deployment.runtime_scope import (
            RuntimeLifecycleStatus,
        )

        entry = MagicMock()
        entry.status = RuntimeLifecycleStatus.RUNNING
        entry.scope = MagicMock(scope_key="k", broker_code="KIWOOM")
        rt_mgr.list_entries.return_value = [entry]
        kill_cls.return_value.is_active.return_value = False
        runner_mgr.get.return_value = None

        out = await restore_kiwoom_trading_stack(
            session,
            user_broker_account_id=1381,
            actor="SYSTEM",
        )

    worker_rt.start.assert_called_once()
    assert out["detail"]["worker"]["started"] is True
    assert out["restored"] is True
