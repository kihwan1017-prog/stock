# -*- coding: utf-8 -*-
"""Offline analysis helpers for counterfactual — NEVER used in trading."""

from __future__ import annotations

from statistics import median
from typing import Any

LOOKAHEAD_ANALYTICS_ONLY = True
MUST_NOT_DRIVE_TRADING = True


def analyze_selected_vs_universe(
    rows: list[dict[str, Any]],
    *,
    horizon_m: int = 15,
) -> dict[str, Any]:
    """Compute selected vs universe forward stats from raw CF rows.

    Expected row keys: symbol, selected, horizon_m, forward_return_pct, status
    Only status=AVAILABLE rows with non-null forward_return_pct are used.
    """

    usable = [
        r
        for r in rows
        if int(r.get("horizon_m") or 0) == int(horizon_m)
        and str(r.get("status") or "") == "AVAILABLE"
        and r.get("forward_return_pct") is not None
    ]
    if not usable:
        return {
            "horizon_m": horizon_m,
            "status": "SOURCE_DATA_MISSING",
            "selected_return": None,
            "universe_mean_return": None,
            "universe_median_return": None,
            "selected_percentile_rank": None,
            "top_candidate_forward_rank": None,
            "selected_was_top_forward_performer": None,
            "lookahead_forbidden_for_trading": True,
        }

    returns = sorted(
        ((str(r["symbol"]).upper(), float(r["forward_return_pct"]), bool(r.get("selected")))
         for r in usable),
        key=lambda x: x[1],
        reverse=True,
    )
    values = [v for _s, v, _sel in returns]
    selected = [r for r in returns if r[2]]
    selected_return = selected[0][1] if selected else None
    selected_symbol = selected[0][0] if selected else None

    # percentile: fraction of universe with return <= selected
    pct_rank = None
    if selected_return is not None and values:
        le = sum(1 for v in values if v <= selected_return)
        pct_rank = round(100.0 * le / len(values), 4)

    top_rank = None
    was_top = None
    if selected_symbol:
        for i, (sym, _v, _sel) in enumerate(returns, start=1):
            if sym == selected_symbol:
                top_rank = i
                was_top = i == 1
                break

    return {
        "horizon_m": horizon_m,
        "status": "AVAILABLE",
        "n_universe": len(values),
        "selected_symbol": selected_symbol,
        "selected_return": selected_return,
        "universe_mean_return": round(sum(values) / len(values), 8),
        "universe_median_return": float(median(values)),
        "selected_percentile_rank": pct_rank,
        "top_candidate_forward_rank": top_rank,
        "selected_was_top_forward_performer": was_top,
        "lookahead_forbidden_for_trading": True,
        "used_in_trading_decision": False,
    }
