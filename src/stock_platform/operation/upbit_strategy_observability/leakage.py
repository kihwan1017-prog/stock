# -*- coding: utf-8 -*-
"""Look-ahead leakage guards — analytics fields never enter trading payloads."""

from __future__ import annotations

from typing import Any

# Keys that must never appear in trading decision metadata / admission / signals
FORBIDDEN_LOOKAHEAD_KEYS = frozenset(
    {
        "post_exit_json",
        "post_exit_return",
        "forward_return",
        "fwd_5m_pct",
        "fwd_15m_pct",
        "fwd_30m_pct",
        "fwd_60m_pct",
        "mfe_pct",
        "mae_pct",
        "time_to_mfe_seconds",
        "time_to_mae_seconds",
        "lookahead_forbidden_for_trading",
        "post_exit_max_return_15m",
        "post_exit_max_return_30m",
        "candidate_counterfactual_forward",
    }
)


def assert_no_lookahead_in_trading_payload(payload: dict[str, Any] | None) -> None:
    """Raise AssertionError if look-ahead analytics keys leak into trading payload."""

    if not isinstance(payload, dict):
        return
    stack: list[Any] = [payload]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                lk = str(k).lower()
                if k in FORBIDDEN_LOOKAHEAD_KEYS or lk.startswith("fwd_") or lk.startswith(
                    "post_exit"
                ):
                    raise AssertionError(
                        f"LOOKAHEAD_LEAKAGE_IN_TRADING_PAYLOAD key={k}"
                    )
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)


def trading_modules_must_not_import_post_trade() -> tuple[str, ...]:
    """Documented forbidden importers for post-trade analytics module."""

    return (
        "stock_platform.trading.entry_admission_service",
        "stock_platform.realtime.ma_evaluator",
        "stock_platform.realtime.risk_integrated_order_executor",
        "stock_platform.order.live_safety_pipeline",
        "stock_platform.order.execution_service",
    )
