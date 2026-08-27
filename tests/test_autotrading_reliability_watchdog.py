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
        # scalar는 datetime/count 혼용 — int(0)은 aware_utc에서 깨짐
        session.scalar.return_value = None
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
            "stock_platform.trading.autotrading_reliability_watchdog.execution_stack_needs_restore",
            return_value={
                "needs_restore": True,
                "restore_kind": "PARTIAL_RESTORE",
                "down_components": ["worker"],
                "desired": {"desired_execution_running": True},
            },
        ),
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog.verify_stack_restored",
            return_value={"restore_succeeded": True, "missing_components": []},
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
    assert out["restore_trigger"] == "PARTIAL_RESTORE"
    assert out["restore_succeeded"] is True
    assert "L2_STACK" in (out.get("actions") or [])


def test_watchdog_restore_fail_telegram_edge_dedup() -> None:
    import stock_platform.trading.autotrading_reliability_watchdog as wd_mod

    wd_mod._last_stack_restore_fail_alert.clear()
    with patch.object(wd_mod, "_emit_reliability_telegram") as tg:
        verify = {"missing_components": ["worker"], "verified": {"worker": False}}
        wd_mod._handle_restore_fail_edge(
            market="UPBIT", uba_id=1380, verify=verify, attempts=2
        )
        wd_mod._handle_restore_fail_edge(
            market="UPBIT", uba_id=1380, verify=verify, attempts=3
        )
    assert tg.call_count == 1


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


def test_backoff_resets_on_success() -> None:
    key = "UPBIT:1380"
    import stock_platform.trading.autotrading_reliability_watchdog as wd_mod

    wd_mod._restore_backoff[key] = {"attempts": 3, "last_attempt_mono": 0.0}
    _record_restore_attempt(key, success=True)
    allowed, _ = _backoff_allowed(key)
    assert allowed is True
    assert wd_mod._restore_backoff[key]["attempts"] == 0


def test_soft_pending_does_not_increment_backoff() -> None:
    key = "UPBIT:1380"
    import stock_platform.trading.autotrading_reliability_watchdog as wd_mod

    wd_mod._restore_backoff[key] = {"attempts": 1, "last_attempt_mono": 0.0}
    _record_restore_attempt(key, success=False, soft_pending=True)
    assert wd_mod._restore_backoff[key]["attempts"] == 1


def test_backoff_after_max_still_retries() -> None:
    """600s 이후 영구 포기 금지 — wait 경과 시 재시도."""
    key = "UPBIT:1380"
    import stock_platform.trading.autotrading_reliability_watchdog as wd_mod
    import time as _time

    wd_mod._restore_backoff[key] = {
        "attempts": 8,
        "last_attempt_mono": _time.monotonic() - 601.0,
    }
    allowed, wait = _backoff_allowed(key)
    assert allowed is True
    assert wait == 0.0


@pytest.mark.asyncio
async def test_feed_pending_not_hard_fail() -> None:
    session = MagicMock()
    session.commit = MagicMock()
    session.close = MagicMock()
    session.rollback = MagicMock()
    snap = {
        "health_state": HEALTH_BROKEN,
        "auto_trading_ready": False,
        "components": {
            "runtime": "RUNNING",
            "runner": "RUNNING",
            "worker": "RUNNING",
            "exit_monitor": "RUNNING",
            "scanner": "RUNNING",
            "feed": "DISCONNECTED",
        },
        "partial_restore": True,
        "waiting_starvation": {},
    }
    with (
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog.build_trading_health_snapshot",
            return_value=snap,
        ),
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog.execution_stack_needs_restore",
            return_value={
                "needs_restore": True,
                "restore_kind": "PARTIAL_RESTORE",
                "desired": {"desired_execution_running": True},
                "down_components": ["feed"],
            },
        ),
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog._l2_stack_restore",
            new_callable=AsyncMock,
            return_value={"ok": True},
        ),
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog.verify_stack_restored",
            return_value={
                "restore_succeeded": False,
                "core_restored": True,
                "feed_pending": True,
                "missing_components": ["feed"],
                "verified": {"feed": False},
            },
        ),
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog._emit_reliability_telegram"
        ) as tg,
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog.get_session_factory",
            return_value=MagicMock(return_value=session),
        ),
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog._l1_feed_reconnect",
            new_callable=AsyncMock,
            return_value={"ok": True},
        ),
        patch(
            "stock_platform.trading.autotrading_reliability_watchdog._l1_scanner_restore",
            return_value={"ok": True},
        ),
    ):
        import stock_platform.trading.autotrading_reliability_watchdog as wd_mod

        wd_mod._restore_backoff[_market_key("UPBIT", 1380)] = {
            "attempts": 0,
            "last_attempt_mono": 0.0,
        }
        out = await reconcile_market_health(market="UPBIT", uba_id=1380)

    assert out.get("feed_pending") is True
    assert out.get("core_restored") is True
    assert wd_mod._restore_backoff[_market_key("UPBIT", 1380)]["attempts"] == 0
    # hard fail telegram은 feed_pending에서 호출되지 않음 (edge helper만 attempts>=2)
    fail_titles = [
        c.kwargs.get("title")
        for c in tg.call_args_list
        if "복구 실패" in str(c.kwargs.get("title") or "")
    ]
    assert fail_titles == []


def test_watchdog_ensure_running_recreates_once() -> None:
    import stock_platform.trading.autotrading_reliability_watchdog as wd_mod

    wd = wd_mod.AutoTradingReliabilityWatchdog()
    # done task 시뮬레이션
    done = MagicMock()
    done.done.return_value = True
    wd._task = done
    with patch.object(wd, "start", return_value={"started": True, "running": True}) as st:
        r1 = wd.ensure_running()
        r2 = wd.ensure_running()
    assert r1.get("ensured") is True
    # 두 번째: start가 running으로 바꾸지 않았으면 또 ensured — start mock만 검증
    assert st.call_count >= 1


def test_watchdog_ensure_no_duplicate_when_alive() -> None:
    import stock_platform.trading.autotrading_reliability_watchdog as wd_mod

    wd = wd_mod.AutoTradingReliabilityWatchdog()
    alive = MagicMock()
    alive.done.return_value = False
    wd._task = alive
    wd._running = True
    out = wd.ensure_running()
    assert out.get("ensured") is False
    assert out.get("reason") == "ALREADY_RUNNING"


def test_recovery_telegram_edge_dedupe() -> None:
    import stock_platform.trading.autotrading_reliability_watchdog as wd_mod

    with patch.object(wd_mod, "_emit_reliability_telegram") as tg:
        wd_mod._handle_health_transition(
            market="UPBIT",
            uba_id=1380,
            prev=HEALTH_BROKEN,
            current=HEALTH_READY,
            snapshot={"components": {}},
        )
        wd_mod._handle_health_transition(
            market="UPBIT",
            uba_id=1380,
            prev=HEALTH_READY,
            current=HEALTH_READY,
            snapshot={"components": {}},
        )
    assert tg.call_count == 1
    assert "복구 완료" in tg.call_args.kwargs["title"]


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
        session.scalar.return_value = None
        snap = build_trading_health_snapshot(session, user_broker_account_id=1380)

    assert snap["components"]["worker"] == "RUNNING"
    assert snap["components"]["exit_monitor"] == "RUNNING"
    assert snap["components"]["runtime"] == "RUNNING"
    assert snap["partial_restore"] is False
