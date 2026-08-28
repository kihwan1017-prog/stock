"""Tests — observability cleanup P1/P2/P3 (focused)."""

from __future__ import annotations

from stock_platform.operation.autotrading_daily_report_service import (
    _health_class,
    _is_kiwoom_expected_post_close,
)
from stock_platform.trading.autotrading_data_trust import evaluate_data_trust_from_health
from stock_platform.trading.autotrading_no_trade_classification import (
    classify_no_trade_status,
)


def test_kiwoom_expected_post_close_not_red() -> None:
    ops = {
        "krx_session_phase": "CLOSED",
        "live": "OFF",
        "market_feed": {"status": "DISCONNECTED"},
        "auto_trading_state": "STOPPED",
        "reliability": {"kiwoom_funnel": {"FIRST_ZERO_STAGE": "MARKET_CLOSED"}},
    }
    assert _is_kiwoom_expected_post_close(ops) is True
    code, _ = _health_class(
        broker="KIWOOM",
        ops=ops,
        order_stats={"buy_order_count": 0},
    )
    assert code != "RED"


def test_kiwoom_regular_feed_failure_orange() -> None:
    ops = {
        "krx_session_phase": "REGULAR",
        "live": "ON",
        "market_feed": {"status": "DISCONNECTED"},
        "reliability": {"health_state": "DEGRADED"},
    }
    code, _ = _health_class(
        broker="KIWOOM", ops=ops, order_stats={"buy_order_count": 0}
    )
    assert code in {"ORANGE", "RED"}


def test_slot_full_waiting_not_pipeline_stall() -> None:
    out = classify_no_trade_status(
        health_state="READY",
        partial_restore=False,
        stack_components_down=False,
        daily_blocking=False,
        free_slots=0,
        waiting_count=3,
        selection_count_window=5,
        candidate_count_window=10,
        order_count_window=0,
        admission_count_window=0,
        feed_healthy=True,
        scanner_active=True,
        pipeline_stall_minutes=15,
        last_order_at=None,
        last_selection_at=None,
    )
    assert out["classification"] == "NORMAL_POLICY_BLOCK"
    assert out["detail"]["reason"] == "SLOT_FULL_WAITING"


def test_policy_block_data_trust_valid() -> None:
    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "RUNNING",
                "feed": "REAL_FRESH",
                "scanner": "RUNNING",
            },
            "no_trade_classification": "NORMAL_POLICY_BLOCK",
            "first_zero_stage": "WAITING",
            "first_zero_reason": "SLOT_FULL_WAITING",
            "health_state": "READY",
            "invariants": {},
            "watchdog": {"running": True},
        }
    )
    assert ev["quality_status"] == "VALID"


def test_silent_gap_still_degraded() -> None:
    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "RUNNING",
                "feed": "REAL_FRESH",
                "scanner": "RUNNING",
            },
            "no_trade_classification": "PIPELINE_STALL",
            "first_zero_stage": "ORDER",
            "health_state": "READY",
            "invariants": {},
            "watchdog": {"running": True},
        }
    )
    assert ev["quality_status"] == "DEGRADED"
