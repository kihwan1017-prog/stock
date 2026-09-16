"""24x7 ops health must expose exit last_evaluated_at for reliability heartbeats."""

from __future__ import annotations

from stock_platform.trading.upbit_24x7_control import build_24x7_ops_health


def test_live_exit_monitor_includes_last_evaluated_at() -> None:
    payload = build_24x7_ops_health()
    assert "live_exit_monitor" in payload
    assert "last_evaluated_at" in payload["live_exit_monitor"]
