"""Focused tests — UBA Truth Layer helpers."""

from __future__ import annotations

from stock_platform.trading.uba_truth_layer import (
    append_arm_renewal_history,
    classify_order_exit_provenance,
)


def test_waiting_signal_not_classified_as_strategy_exit() -> None:
    assert classify_order_exit_provenance({}) == "UNKNOWN"


def test_ma_dead_cross_is_strategy_exit() -> None:
    assert (
        classify_order_exit_provenance(
            {"signal_reason": "MA_DEAD_CROSS", "source": "REALTIME_SIGNAL"}
        )
        == "STRATEGY_EXIT"
    )


def test_protective_monitor_stop_loss() -> None:
    assert (
        classify_order_exit_provenance(
            {"exit_reason": "STOP_LOSS", "source": "POSITION_EXIT_MONITOR"}
        )
        == "STOP_LOSS"
    )


def test_arm_renewal_history_appends() -> None:
    d1 = append_arm_renewal_history({}, entry={"at": "t1"})
    d2 = append_arm_renewal_history(d1, entry={"at": "t2"})
    assert d2["arm_renewed"] is True
    assert len(d2["arm_renewal_history"]) == 2
    assert d2["arm_renewal_history"][-1]["at"] == "t2"
