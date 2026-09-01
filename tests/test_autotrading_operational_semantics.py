"""Focused tests — operational status semantics + exit pending watchdog."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.autotrading_operational_semantics import (
    INFORMATIONAL_FIRST_ZERO_REASONS,
    classify_operational_status,
    is_informational_first_zero,
)
from stock_platform.trading.autotrading_reliability_watchdog import (
    _handle_exit_stuck_transition,
    _last_exit_stuck_alert,
    _last_exit_stuck_tiers,
)


def test_exit_pending_infra_healthy_entry_restricted_not_system_blocked() -> None:
    sem = classify_operational_status(
        live_on=True,
        arm_on=True,
        activation_active=True,
        partial_restore=False,
        stack_down=False,
        feed_healthy=True,
        exit_monitor_running=True,
        health_state="READY",
        health_reasons=["EXIT_PENDING_ZERO_FILL_STUCK"],
        blockers=[],
        exit_pending_stuck={
            "stuck": True,
            "items": [{"order_id": 2289, "age_seconds": 300}],
        },
        exit_pending_watchdog={"items": [{"ORDER_ID": 2289}]},
    )
    assert sem["operational_tier"] == "ENTRY_RESTRICTED"
    assert sem["system_blocked"] is False
    assert sem["entry_restricted"] is True


def test_arm_off_system_blocked() -> None:
    sem = classify_operational_status(
        live_on=True,
        arm_on=False,
        activation_active=True,
        partial_restore=False,
        stack_down=False,
        feed_healthy=True,
        exit_monitor_running=True,
        health_state="DEGRADED",
        health_reasons=["LIVE_ARM_ACTIVATION_INCOMPLETE"],
        blockers=["ARM_OFF"],
    )
    assert sem["operational_tier"] == "SYSTEM_BLOCKED"
    assert sem["system_blocked"] is True


def test_ambiguous_sell_system_blocked() -> None:
    sem = classify_operational_status(
        live_on=True,
        arm_on=True,
        activation_active=True,
        partial_restore=False,
        stack_down=False,
        feed_healthy=True,
        exit_monitor_running=True,
        health_state="DEGRADED",
        health_reasons=[],
        blockers=[],
        ambiguous_open=True,
        exit_pending_stuck={"stuck": True, "items": [{}]},
    )
    assert sem["operational_tier"] == "SYSTEM_BLOCKED"
    assert "AMBIGUOUS_ORDER" in sem["system_blockers"]


def test_informational_first_zero_not_system_blocked() -> None:
    assert is_informational_first_zero("NO_CANDIDATE_SNAPSHOT", health_state="READY")
    sem = classify_operational_status(
        live_on=True,
        arm_on=True,
        activation_active=True,
        partial_restore=False,
        stack_down=False,
        feed_healthy=True,
        exit_monitor_running=True,
        health_state="READY",
        health_reasons=[],
        blockers=[],
        first_zero_reason="NO_CANDIDATE_SNAPSHOT",
    )
    assert sem["operational_tier"] == "RUNNING"
    assert sem["informational_first_zero"] is True


def test_exit_pending_infra_down_system_blocked() -> None:
    sem = classify_operational_status(
        live_on=True,
        arm_on=True,
        activation_active=True,
        partial_restore=False,
        stack_down=True,
        feed_healthy=True,
        exit_monitor_running=False,
        health_state="BROKEN",
        health_reasons=["EXIT_PENDING_ZERO_FILL_STUCK", "EXECUTION_STACK_DOWN"],
        blockers=["EXECUTION_STACK_DOWN"],
        exit_pending_stuck={"stuck": True, "items": [{}]},
    )
    assert sem["operational_tier"] == "SYSTEM_BLOCKED"


def test_alert_dedupe_tiered(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted: list[str] = []

    def _fake_emit(**kwargs):  # noqa: ANN003
        emitted.append(str(kwargs.get("event_type")))

    monkeypatch.setattr(
        "stock_platform.trading.autotrading_reliability_watchdog._emit_reliability_telegram",
        _fake_emit,
    )
    _last_exit_stuck_tiers.clear()
    _last_exit_stuck_alert.clear()
    snap = {
        "exit_pending_stuck": {
            "stuck": True,
            "items": [{"order_id": 1, "symbol": "KRW-X", "age_seconds": 700}],
        }
    }
    _handle_exit_stuck_transition(
        market="UPBIT", uba_id=1380, stuck=True, snapshot=snap
    )
    _handle_exit_stuck_transition(
        market="UPBIT", uba_id=1380, stuck=True, snapshot=snap
    )
    assert emitted.count("UPBIT_EXIT_PENDING_ZERO_FILL") == 1
    assert "UPBIT_EXIT_PENDING_LONG_WAIT" in emitted

    _handle_exit_stuck_transition(
        market="UPBIT",
        uba_id=1380,
        stuck=False,
        snapshot=snap,
    )
    assert "UPBIT_EXIT_PENDING_RECOVERED" in emitted

