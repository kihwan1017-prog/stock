# -*- coding: utf-8 -*-
"""Upbit AUTO strategy observability V1 — OBSERVATION ONLY.

Trading decisions must never depend on these writers or post-trade fields.
Look-ahead (forward returns / post-exit prices) is analytics-only.
"""

from __future__ import annotations

__all__ = [
    "observe_scanner_universe",
    "observe_admission",
    "observe_signal_event",
    "observe_exit_event",
    "observe_order_timeline_stamp",
    "compute_post_trade_analytics_safe",
    "assert_no_lookahead_in_trading_payload",
]
