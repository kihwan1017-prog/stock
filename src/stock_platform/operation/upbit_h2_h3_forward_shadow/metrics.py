"""Lightweight research metrics — no realtime/apscheduler import chain."""

from __future__ import annotations

import statistics
from typing import Any, Sequence


def net_return_pct(
    gross_return_pct: float,
    *,
    fee_rate: float = 0.0005,
    slip_bps: float = 2.0,
) -> float:
    fee_pct = fee_rate * 2 * 100.0
    slip_pct = (slip_bps / 10000.0) * 2 * 100.0
    return float(gross_return_pct) - fee_pct - slip_pct


def net_pnl_krw(net_ret_pct: float, notional: float = 10000.0) -> float:
    return notional * (net_ret_pct / 100.0)


def profit_factor(nets: Sequence[float]) -> float:
    gains = sum(x for x in nets if x > 0)
    losses = sum(-x for x in nets if x < 0)
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def max_drawdown(nets: Sequence[float]) -> float:
    peak = 0.0
    equity = 0.0
    mdd = 0.0
    for x in nets:
        equity += float(x)
        peak = max(peak, equity)
        mdd = max(mdd, peak - equity)
    return float(mdd)


def summarize_nets(nets: Sequence[float], *, days: float) -> dict[str, Any]:
    xs = [float(x) for x in nets]
    n = len(xs)
    if n == 0:
        return {
            "n": 0,
            "opportunities_day": 0.0,
            "win_rate": None,
            "pf": None,
            "total_net": 0.0,
            "mdd": 0.0,
        }
    wins = sum(1 for x in xs if x > 0)
    d = max(float(days), 1.0)
    pf = profit_factor(xs)
    return {
        "n": n,
        "opportunities_day": round(n / d, 2),
        "win_rate": round(100.0 * wins / n, 1),
        "pf": None if pf == float("inf") else round(pf, 3),
        "avg_net_trade": round(statistics.fmean(xs), 2),
        "total_net": round(sum(xs), 2),
        "mdd": round(max_drawdown(xs), 2),
    }
