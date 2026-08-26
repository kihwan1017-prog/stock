"""AutoTrading reliability watchdog + health SoT tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.trading.autotrading_health_service import (
    HEALTH_BROKEN,
    HEALTH_READY,
    build_trading_health_snapshot,
)
from stock_platform.trading.autotrading_no_trade_classification import (
    classify_no_trade_status,
)
from stock_platform.trading.autotrading_reliability_watchdog import (
    _backoff_allowed,
    _market_key,
    _record_restore_attempt,
    reconcile_market_health,
    record_stack_forensic,
)


def test_partial_restore_detected_in_health_snapshot() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        user_id=61,
    )
    session.get.return_value = uba

    with (
        patch(
            "stock_platform.trading.autotrading_health_service.combined_control_status",
            return_value={
                "strategy_runtime": "STOPPED",
                "outbox_worker": "STOPPED",
                "exit_monitor": "STOPPED",
                "activation": "ACTIVE",
                "runtime": {},
                "worker": {},
                "exit_monitor_detail": {},
            },
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.build_24x7_ops_health",
            return_value={
                "strategy_runtime": {"status": "STOPPED"},
                "live_outbox_worker": {"status": "STOPPED"},
                "live_exit_monitor": {"status": "STOPPED"},
            },
        ),
        patch(
            "stock_platform.trading.autotrading_health_service.LiveTradingTransitionService"
        ) as act_svc,
        patch(
            "stock_platform.trading.autotrading_health_service.LiveUnattendedAuthorizationService"
        ),
        patch(
            "stock_platform.trading.autotrading_health_service._runner_status_for_uba",
            return_value=("STOPPED", {}),
        ),
        patch(
            "stock_platform.trading.autotrading_master_gate.evaluate_uba_autotrading_ready",
            return_value={"blockers": ["STRATEGY_RUNTIME_NOT_RUNNING"], "checks": {}},
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission.resolve_portfolio_daily_entry_limit",
            return_value=20,
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_count.summarize_portfolio_daily_entries",
            return_value={
                "entry_count": 0,
                "entry_limit": 20,
                "remaining": 20,
                "blocking": False,
            },
        ),
        patch(
            "stock_platform.trading.upbit_funnel_observability.build_upbit_funnel_snapshot",
            return_value={
                "stages": {"SELECTION": 3, "ORDER": 0, "CANDIDATE": 2},
                "first_zero_stage": "ORDER",
            },
        ),
        patch(
            "stock_platform.operation.upbit_opportunity_scanner.scheduler.upbit_opportunity_scanner_scheduler"
        ) as sc_mod,
    ):
        act_svc.return_value.peek_active.return_value = object()
        sc_mod.status.return_value = {"running": False, "started": False}
        session.execute.return_value.mappings.return_value.all.return_value = []
        session.scalar.return_value = 0
        snap = build_trading_health_snapshot(session, user_broker_account_id=1380)

    assert snap["partial_restore"] is True
    assert snap["health_state"] == HEALTH_BROKEN
    assert snap["no_trade_classification"] == "SYSTEM_FAILURE"


def test_classify_normal_no_signal() -> None:
    out = classify_no_trade_status(
        health_state=HEALTH_READY,
        partial_restore=False,
        stack_components_down=False,
        daily_blocking=False,
        free_slots=2,
        waiting_count=0,
        selection_count_window=0,
        candidate_count_window=0,
        order_count_window=0,
        feed_healthy=True,
        scanner_active=True,
        pipeline_stall_minutes=15,
        last_order_at=None,
        last_selection_at=None,
    )
    assert out["classification"] == "NORMAL_NO_SIGNAL"


def test_classify_system_failure_waiting_stack_down() -> None:
    out = classify_no_trade_status(
        health_state=HEALTH_BROKEN,
        partial_restore=True,
        stack_components_down=True,
        daily_blocking=False,
        free_slots=0,
        waiting_count=5,
        selection_count_window=5,
        candidate_count_window=3,
        order_count_window=0,
        feed_healthy=False,
        scanner_active=False,
        pipeline_stall_minutes=15,
        last_order_at=None,
        last_selection_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert out["classification"] == "SYSTEM_FAILURE"


def test_classify_daily_policy_block() -> None:
    out = classify_no_trade_status(
        health_state=HEALTH_READY,
        partial_restore=False,
        stack_components_down=False,
        daily_blocking=True,
        free_slots=0,
        waiting_count=0,
        selection_count_window=0,
        candidate_count_window=0,
        order_count_window=0,
        feed_healthy=True,
        scanner_active=True,
        pipeline_stall_minutes=15,
        last_order_at=None,
        last_selection_at=None,
    )
    assert out["classification"] == "NORMAL_POLICY_BLOCK"


@pytest.mark.asyncio
async def test_l2_restore_on_partial_restore() -> None:
    session = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()

    snap = {
        "health_state": HEALTH_BROKEN,
        "partial_restore": True,
        "live": "ON",
        "arm": "ON",
        "activation": "ACTIVE",
        "components": {
            "runtime": "STOPPED",
            "runner": "STOPPED",
            "worker": "STOPPED",
            "exit_monitor": "STOPPED",
            "feed": "DISCONNECTED",
            "scanner": "STOPPED",
        },
        "blockers": [],
        "kiwoom_stack_slo_active": True,
    }
    post_snap = {
        **snap,
        "health_state": HEALTH_READY,
        "auto_trading_ready": True,
        "components": {
            "runtime": "RUNNING",
            "runner": "RUNNING",
            "worker": "RUNNING",
            "exit_monitor": "RUNNING",
            "feed": "REAL_FRESH",
            "scanner": "RUNNING",
        },
    }

    with (
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog.get_session_factory"
        ) as sf,
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog.build_trading_health_snapshot",
            side_effect=[snap, post_snap],
        ),
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog._l1_feed_reconnect",
            new_callable=AsyncMock,
            return_value={"ok": True},
        ),
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog._l1_scanner_restore",
            return_value={"started": True},
        ),
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog._l2_stack_restore",
            new_callable=AsyncMock,
            return_value={"restored": True, "detail": {"component_ok": {}}},
        ),
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog._emit_reliability_telegram"
        ),
    ):
        sf.return_value = MagicMock(return_value=session)
        import stock_platform.trading.autotrading_reliability_watchdog as wd_mod

        wd_mod._restore_backoff[_market_key("UPBIT", 1380)] = {"attempts": 0}
        out = await reconcile_market_health(market="UPBIT", uba_id=1380)

    assert out["restore_attempted"] is True
    assert out["restore_trigger"] == "WATCHDOG"
    assert out["restore_succeeded"] is True
    assert "L2_STACK" in (out.get("actions") or [])


def test_backoff_increases_on_failure() -> None:
    key = "UPBIT:1380"
    import stock_platform.trading.autotrading_reliability_watchdog as wd_mod

    wd_mod._restore_backoff[key] = {"attempts": 0, "last_attempt_mono": 0.0}
    allowed, _ = _backoff_allowed(key)
    assert allowed is True
    _record_restore_attempt(key, success=False)
    allowed2, wait = _backoff_allowed(key)
    assert allowed2 is False
    assert wait > 0


def test_stack_forensic_ring_buffer() -> None:
    record_stack_forensic(
        market="UPBIT",
        uba_id=1380,
        component="runtime",
        event="STOP",
        reason="TEST",
    )
    from stock_platform.trading.autotrading_reliability_watchdog import (
        get_stack_forensic,
    )

    events = get_stack_forensic(market="UPBIT", uba_id=1380)
    assert events[-1]["component"] == "runtime"
    assert events[-1]["event"] == "STOP"


def test_health_ops_alignment_when_ops_running() -> None:
    """/health/ops(upbit_24x7)와 health SoT component 상태 일치."""
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        user_id=61,
    )
    session.get.return_value = uba

    with (
        patch(
            "stock_platform.trading.autotrading_health_service.combined_control_status",
            return_value={
                "strategy_runtime": "STOPPED",
                "outbox_worker": "STOPPED",
                "exit_monitor": "STOPPED",
                "activation": "ACTIVE",
                "runtime": {},
                "worker": {},
                "exit_monitor_detail": {},
            },
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.build_24x7_ops_health",
            return_value={
                "strategy_runtime": {"status": "RUNNING"},
                "live_outbox_worker": {"status": "RUNNING", "last_run_at": "2026-01-01T00:00:00+00:00"},
                "live_exit_monitor": {"status": "RUNNING"},
            },
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.runtime_status_for_uba",
            return_value={"status": "STOPPED", "entries": []},
        ),
        patch(
            "stock_platform.trading.autotrading_health_service.LiveTradingTransitionService"
        ) as act_svc,
        patch(
            "stock_platform.trading.autotrading_health_service._runner_status_for_uba",
            return_value=("RUNNING", {"heartbeat": "2026-01-01T00:00:00+00:00"}),
        ),
        patch(
            "stock_platform.trading.autotrading_master_gate.evaluate_uba_autotrading_ready",
            return_value={"blockers": [], "checks": {"market_feed": {"status": "REAL_FRESH"}}},
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission.resolve_portfolio_daily_entry_limit",
            return_value=20,
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_count.summarize_portfolio_daily_entries",
            return_value={
                "entry_count": 0,
                "entry_limit": 20,
                "remaining": 20,
                "blocking": False,
            },
        ),
        patch(
            "stock_platform.trading.upbit_funnel_observability.build_upbit_funnel_snapshot",
            return_value={"stages": {}, "first_zero_stage": "ORDER"},
        ),
        patch(
            "stock_platform.operation.upbit_opportunity_scanner.scheduler.upbit_opportunity_scanner_scheduler"
        ) as sc_mod,
    ):
        act_svc.return_value.peek_active.return_value = object()
        sc_mod.status.return_value = {"running": True, "started": True}
        session.execute.return_value.mappings.return_value.all.return_value = []
        session.scalar.return_value = 0
        snap = build_trading_health_snapshot(session, user_broker_account_id=1380)

    assert snap["components"]["worker"] == "RUNNING"
    assert snap["components"]["exit_monitor"] == "RUNNING"
    assert snap["components"]["runtime"] == "RUNNING"
    assert snap["partial_restore"] is False
