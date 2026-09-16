"""Kiwoom UBA1381 AUTO blocker remediation — focused regression tests."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.realtime.risk_aware_entry_sizing import (
    resolve_risk_aware_entry_size,
)
from stock_platform.strategy_deployment.runtime_scope import (
    RuntimeLifecycleStatus,
)
from stock_platform.trading.entry_stack_pause_authority import (
    evaluate_kiwoom_entry_stack_hold,
    is_explicit_entry_pause_reason,
)
from stock_platform.trading.execution_stack_reconciliation import (
    execution_stack_needs_restore,
)
from stock_platform.trading.trading_scheduler_control import (
    reset_trading_scheduler_control_for_tests,
    set_trading_scheduler_desired_state,
)


def test_explicit_pause_reason_blocks_auto_resume() -> None:
    assert is_explicit_entry_pause_reason("OPERATOR_PAUSE") is True
    assert is_explicit_entry_pause_reason("SAFETY_PAUSE") is True
    assert is_explicit_entry_pause_reason(
        "KIWOOM_UBA1381_POST_SMOKE_RUNTIME_STATE_ALIGNMENT"
    ) is True
    assert is_explicit_entry_pause_reason("admin_pause") is True
    assert is_explicit_entry_pause_reason("reloaded_paused") is False
    assert is_explicit_entry_pause_reason(None) is False


def test_scheduler_pause_holds_kiwoom_entry_stack() -> None:
    reset_trading_scheduler_control_for_tests()
    set_trading_scheduler_desired_state("PAUSE", actor="test")
    with patch(
        "stock_platform.trading.entry_stack_pause_authority."
        "dynamic_strategy_runtime_manager.list_entries",
        return_value=[],
    ):
        hold = evaluate_kiwoom_entry_stack_hold(
            None, user_broker_account_id=1381
        )
    assert hold["hold"] is True
    assert "SCHEDULER_DESIRED_PAUSE" in hold["reasons"]
    reset_trading_scheduler_control_for_tests()


def test_explicit_scoped_pause_holds_even_if_scheduler_run() -> None:
    reset_trading_scheduler_control_for_tests()
    set_trading_scheduler_desired_state("RUN", actor="test")
    entry = SimpleNamespace(
        status=RuntimeLifecycleStatus.PAUSED,
        pause_reason="OPERATOR_PAUSE",
        scope=SimpleNamespace(
            broker_code="KIWOOM",
            scope_key="uba:1381:s:17579",
        ),
    )
    with patch(
        "stock_platform.trading.entry_stack_pause_authority."
        "dynamic_strategy_runtime_manager.list_entries",
        return_value=[entry],
    ):
        hold = evaluate_kiwoom_entry_stack_hold(
            None, user_broker_account_id=1381, strategy_id=17579
        )
    assert hold["hold"] is True
    assert "EXPLICIT_SCOPED_RUNTIME_PAUSE" in hold["reasons"]
    reset_trading_scheduler_control_for_tests()


def test_needs_restore_excludes_kiwoom_entry_when_held() -> None:
    reset_trading_scheduler_control_for_tests()
    set_trading_scheduler_desired_state("PAUSE", actor="test")
    session = MagicMock()
    snap = {
        "components": {
            "runtime": "PAUSED",
            "runner": "STOPPED",
            "worker": "RUNNING",
            "exit_monitor": "RUNNING",
            "scanner": "RUNNING",
            "feed": "REAL_FRESH",
        },
        "health_state": "DEGRADED",
        "partial_restore": True,
    }
    with (
        patch(
            "stock_platform.trading.execution_stack_reconciliation."
            "evaluate_desired_execution_state",
            return_value={
                "desired_execution_running": True,
                "broker": "KIWOOM",
                "components": {k: "RUNNING" for k in snap["components"]},
            },
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation."
            "build_trading_health_snapshot",
            return_value=snap,
        ),
        patch(
            "stock_platform.trading.entry_stack_pause_authority."
            "dynamic_strategy_runtime_manager.list_entries",
            return_value=[],
        ),
    ):
        need = execution_stack_needs_restore(
            session, user_broker_account_id=1381, snapshot=snap
        )
    assert need["needs_restore"] is False
    assert need["down_components"] == []
    assert need["entry_stack_hold"]["hold"] is True
    reset_trading_scheduler_control_for_tests()


def test_upbit_needs_restore_not_blocked_by_scheduler_pause() -> None:
    """UBA1380 isolation — Kiwoom hold logic must not apply to UPBIT."""

    reset_trading_scheduler_control_for_tests()
    set_trading_scheduler_desired_state("PAUSE", actor="test")
    session = MagicMock()
    snap = {
        "components": {
            "runtime": "STOPPED",
            "runner": "STOPPED",
            "worker": "RUNNING",
            "exit_monitor": "RUNNING",
            "scanner": "RUNNING",
            "feed": "REAL_FRESH",
        }
    }
    with (
        patch(
            "stock_platform.trading.execution_stack_reconciliation."
            "evaluate_desired_execution_state",
            return_value={
                "desired_execution_running": True,
                "broker": "UPBIT",
            },
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation."
            "build_trading_health_snapshot",
            return_value=snap,
        ),
    ):
        need = execution_stack_needs_restore(
            session, user_broker_account_id=1380, snapshot=snap
        )
    assert need["needs_restore"] is True
    assert "runtime" in need["down_components"]
    reset_trading_scheduler_control_for_tests()


@pytest.mark.asyncio
async def test_resume_account_runtimes_skips_explicit_pause() -> None:
    from stock_platform.strategy_deployment.runtime_manager import (
        DynamicStrategyRuntimeManager,
    )
    from stock_platform.strategy_deployment.runtime_scope import (
        AccountKind,
        StrategyRuntimeScope,
    )

    mgr = DynamicStrategyRuntimeManager()
    scope = StrategyRuntimeScope(
        user_id=1,
        account_kind=AccountKind.USER_BROKER,
        account_id=1381,
        strategy_id=17579,
        strategy_version="1",
        market_type="KRX",
        broker_code="KIWOOM",
        strategy_code="T",
        market_code="KRX",
    )
    entry = SimpleNamespace(
        scope=scope,
        status=RuntimeLifecycleStatus.PAUSED,
        pause_reason="OPERATOR_PAUSE",
        last_started_at=None,
        updated_at=None,
    )
    mgr._runtimes[scope.scope_key] = entry  # type: ignore[attr-defined]
    resumed = await mgr.resume_account_runtimes(
        user_broker_account_id=1381
    )
    assert resumed == []
    assert entry.status == RuntimeLifecycleStatus.PAUSED
    assert entry.pause_reason == "OPERATOR_PAUSE"

def test_canonical_sizing_respects_max_amount_and_qty() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.realtime.risk_aware_entry_sizing."
            "resolve_portfolio_entry_risk_limits"
        ) as lim,
        patch(
            "stock_platform.realtime.risk_aware_entry_sizing."
            "ResolvedRiskPolicyResolver"
        ) as resolver,
    ):
        lim.return_value = SimpleNamespace(
            max_order_amount=Decimal("50000"),
            max_position_amount=Decimal("50000"),
            source_layers=("uba",),
        )
        resolver.return_value.resolve.return_value = SimpleNamespace(
            max_order_quantity=Decimal("1"),
        )
        out = resolve_risk_aware_entry_size(
            session,
            user_broker_account_id=1381,
            user_id=1,
            signal_price=Decimal("12840"),
            nominal_order_amount=Decimal("100000"),
            exchange_code="KRX",
        )
    assert out["ok"] is True
    assert out["quantity"] == Decimal("1")
    assert out["order_amount"] == Decimal("12840")
    assert out["risk_reject_dependency"] is False
    assert out["order_amount"] <= Decimal("50000")


def test_canonical_sizing_blocks_when_price_exceeds_cap() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.realtime.risk_aware_entry_sizing."
            "resolve_portfolio_entry_risk_limits"
        ) as lim,
        patch(
            "stock_platform.realtime.risk_aware_entry_sizing."
            "ResolvedRiskPolicyResolver"
        ) as resolver,
    ):
        lim.return_value = SimpleNamespace(
            max_order_amount=Decimal("10000"),
            max_position_amount=Decimal("10000"),
            source_layers=("uba",),
        )
        resolver.return_value.resolve.return_value = SimpleNamespace(
            max_order_quantity=Decimal("1"),
        )
        out = resolve_risk_aware_entry_size(
            session,
            user_broker_account_id=1381,
            user_id=1,
            signal_price=Decimal("12840"),
            nominal_order_amount=Decimal("100000"),
            exchange_code="KRX",
        )
    assert out["ok"] is False
    assert out["skip_reason"] == "ORDER_AMOUNT_BELOW_EXECUTABLE"


def test_live_skip_risk_checks_disabled_for_live() -> None:
    """소스 계약: LIVE AUTO 는 skip_risk_checks=False."""

    from pathlib import Path

    src = Path(
        "src/stock_platform/realtime/risk_integrated_order_executor.py"
    ).read_text(encoding="utf-8")
    assert "skip_risk_checks=(environment == \"PAPER\")" in src
    assert "skip_risk_checks=True,  # 이미 상단에서 검증" not in src


def test_kiwoom_exit_loader_flag_off_reports_skip() -> None:
    from stock_platform.position.exit_monitor_loader import (
        PositionExitMonitorLoader,
    )

    session = MagicMock()
    loader = PositionExitMonitorLoader(session)
    with patch(
        "stock_platform.position.exit_monitor_loader.get_settings"
    ) as gs:
        gs.return_value = SimpleNamespace(
            position_exit_monitor_live_kiwoom_enabled=False
        )
        positions, skipped = loader._load_kiwoom_strategy_owned_live_positions(
            threshold_by_user={}
        )
    assert positions == []
    assert skipped == ["flag_off:LIVE_KIWOOM"]


def test_kiwoom_exit_loader_strategy_owned_only() -> None:
    from stock_platform.position.exit_monitor_loader import (
        PositionExitMonitorLoader,
    )

    session = MagicMock()
    binding = SimpleNamespace(
        user_broker_account_id=1381,
        symbol="034310",
        owned_quantity=Decimal("1"),
        entry_price=Decimal("12530"),
        binding_id=677,
        ownership_code="STRATEGY_OWNED",
        status="OPEN",
        broker_code="KIWOOM",
    )
    session.scalars.return_value = [binding]
    session.get.return_value = SimpleNamespace(user_id=1)
    loader = PositionExitMonitorLoader(session)

    with (
        patch(
            "stock_platform.position.exit_monitor_loader.get_settings"
        ) as gs,
        patch(
            "stock_platform.broker.recovery_lock.RecoveryAccountLockService"
        ) as lock_cls,
        patch(
            "stock_platform.position.exit_monitor_live.has_blocking_live_exit_sell",
            return_value=False,
        ),
        patch(
            "stock_platform.position.exit_monitor_live.is_live_exit_eligible",
            return_value=(True, "OK"),
        ),
        patch(
            "stock_platform.position.exit_monitor_live.resolve_kiwoom_live_price",
            return_value=Decimal("12840"),
        ),
    ):
        gs.return_value = SimpleNamespace(
            position_exit_monitor_live_kiwoom_enabled=True,
            autotrading_market_feed_stale_seconds=30.0,
        )
        lock_cls.return_value.is_trading_paused.return_value = False
        loader._resolve_thresholds = MagicMock(
            return_value=SimpleNamespace(
                stop_loss_ratio=Decimal("0.05"),
                take_profit_ratio=Decimal("0.10"),
                trailing_stop_ratio=Decimal("0.03"),
                relative_loss_ratio=None,
                trailing_activation_ratio=None,
            )
        )
        positions, skipped = loader._load_kiwoom_strategy_owned_live_positions(
            threshold_by_user={}
        )

    assert len(positions) == 1
    assert positions[0].symbol == "034310"
    assert positions[0].binding_id == 677
    assert positions[0].broker_code == "KIWOOM"
    assert skipped == []


def test_exit_monitor_status_exposes_live_kiwoom_flag() -> None:
    from stock_platform.position.exit_monitor_runtime import (
        PositionExitMonitorManager,
    )

    mgr = PositionExitMonitorManager()
    with patch(
        "stock_platform.position.exit_monitor_runtime.get_settings"
    ) as gs:
        gs.return_value = SimpleNamespace(
            position_exit_monitor_enabled=True,
            position_exit_monitor_interval_seconds=5.0,
            position_exit_monitor_live_upbit_enabled=True,
            position_exit_monitor_live_kiwoom_enabled=False,
        )
        st = mgr.status()
    assert st["live_kiwoom_enabled"] is False
    assert st["live_upbit_enabled"] is True
