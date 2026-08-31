"""Kiwoom stack restore: feed ensure 예외여도 health feed가 fresh면 복구 계속."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.trading.kiwoom_unattended_stack_restore import (
    restore_kiwoom_trading_stack,
)


@pytest.mark.asyncio
async def test_feed_ensure_error_blocks_when_feed_not_fresh() -> None:
    session = MagicMock()
    with (
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
            side_effect=RuntimeError("duplicate singleton probe"),
        ),
        patch(
            "stock_platform.trading.autotrading_health_service.build_trading_health_snapshot",
            return_value={"components": {"feed": "STALE"}},
        ),
    ):
        out = await restore_kiwoom_trading_stack(
            session,
            user_broker_account_id=1381,
            actor="SYSTEM",
        )
    assert out["restored"] is False
    assert out["reason"] == "FEED_START_ERROR"
    assert out["detail"]["feed"].get("continued_despite_error") is not True


@pytest.mark.asyncio
async def test_feed_ensure_error_continues_when_health_feed_fresh() -> None:
    session = MagicMock()
    session.scalar = MagicMock(return_value=None)

    with (
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
            side_effect=RuntimeError("duplicate singleton probe"),
        ),
        patch(
            "stock_platform.trading.autotrading_health_service.build_trading_health_snapshot",
            return_value={"components": {"feed": "REAL_FRESH"}},
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
            return_value={
                "started": True,
                "already_running": False,
                "mode": "LIVE",
                "user_broker_account_id": 1381,
            },
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation.verify_stack_restored",
            return_value={"restore_succeeded": True, "core_restored": True},
        ),
    ):
        kill_cls.return_value.is_active.return_value = False
        link = MagicMock()
        session.scalar = MagicMock(return_value=link)

        running_entry = MagicMock()
        running_entry.status = MagicMock()
        # RuntimeLifecycleStatus.RUNNING 비교용 — enum 값 직접 사용
        from stock_platform.strategy_deployment.runtime_scope import (
            RuntimeLifecycleStatus,
        )

        running_entry.status = RuntimeLifecycleStatus.RUNNING
        running_entry.scope = MagicMock(scope_key="k", broker_code="KIWOOM")
        rt_mgr.list_entries.return_value = [running_entry]
        runner_mgr.get.return_value = None

        out = await restore_kiwoom_trading_stack(
            session,
            user_broker_account_id=1381,
            actor="SYSTEM",
        )

    assert out["detail"]["feed"]["continued_despite_error"] is True
    assert out["detail"]["feed"]["health_feed"] == "REAL_FRESH"
    assert out["restored"] is True
    assert out["reason"] == "OK"
