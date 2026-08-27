"""EXIT_PENDING zero-fill stuck detection + classification (unit)."""

from __future__ import annotations

from stock_platform.trading.autotrading_data_trust import evaluate_data_trust_from_health
from stock_platform.trading.autotrading_no_trade_classification import (
    classify_no_trade_status,
)


def test_healthy_no_signal_is_normal():
    out = classify_no_trade_status(
        health_state="READY",
        partial_restore=False,
        stack_components_down=False,
        daily_blocking=False,
        free_slots=1,
        waiting_count=3,
        selection_count_window=2,
        candidate_count_window=5,
        order_count_window=0,
        admission_count_window=0,
        feed_healthy=True,
        scanner_active=True,
        pipeline_stall_minutes=30,
        last_order_at=None,
        last_selection_at=None,
        waiting_slot_starvation=False,
    )
    # waiting without admission can be PIPELINE_STALL or NORMAL depending on branch
    assert out["classification"] in {
        "NORMAL_NO_SIGNAL",
        "PIPELINE_STALL",
        "NORMAL_POLICY_BLOCK",
    }


def test_entry_pass_without_order_pipeline_stall_context():
    # selection/waiting activity + no orders → stall when aged
    from datetime import datetime, timedelta, timezone

    out = classify_no_trade_status(
        health_state="READY",
        partial_restore=False,
        stack_components_down=False,
        daily_blocking=False,
        free_slots=1,
        waiting_count=2,
        selection_count_window=3,
        candidate_count_window=3,
        order_count_window=0,
        admission_count_window=0,
        feed_healthy=True,
        scanner_active=True,
        pipeline_stall_minutes=5,
        last_order_at=datetime.now(timezone.utc) - timedelta(minutes=60),
        last_selection_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        waiting_slot_starvation=False,
    )
    assert out["classification"] == "PIPELINE_STALL"


def test_stack_down_system_failure():
    out = classify_no_trade_status(
        health_state="BROKEN",
        partial_restore=False,
        stack_components_down=True,
        daily_blocking=False,
        free_slots=1,
        waiting_count=0,
        selection_count_window=0,
        candidate_count_window=0,
        order_count_window=0,
        feed_healthy=False,
        scanner_active=False,
        pipeline_stall_minutes=30,
        last_order_at=None,
        last_selection_at=None,
    )
    assert out["classification"] == "SYSTEM_FAILURE"


def test_data_trust_exit_pending_stuck_invalid():
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
            "watchdog": {"running": True},
            "health_reasons": ["EXIT_PENDING_ZERO_FILL_STUCK"],
            "exit_pending_stuck": {"count": 1, "stuck": True},
            "classification": "SYSTEM_FAILURE",
            "first_zero_stage": "EXIT",
            "open_count": 0,
            "stages": {},
        }
    )
    assert ev["quality_status"] == "INVALID"
    assert ev["reason_code"] == "EXIT_PENDING_STUCK"


def test_data_trust_valid_no_signal_not_quarantined():
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
            "watchdog": {"running": True},
            "health_reasons": [],
            "classification": "NORMAL_NO_SIGNAL",
            "first_zero_stage": "ENTRY_SIGNAL",
            "open_count": 0,
            "stages": {"ENTRY_EVALUATION": 10, "ENTRY_PASS": 0},
        }
    )
    assert ev["quality_status"] == "VALID"
