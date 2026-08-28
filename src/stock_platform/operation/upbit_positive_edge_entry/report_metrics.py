"""Report helpers for WRK-016 opportunity outcomes."""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any, Sequence

from stock_platform.operation.upbit_short_term_turnover.metrics import (
    max_drawdown,
    profit_factor,
)
from stock_platform.operation.upbit_positive_edge_entry.walk_forward import (
    confidence_from_n,
)

FEE_RATE = 0.0005
SLIP_BPS_DEFAULT = 2.0
NOTIONAL = 10000.0
HORIZONS = (5, 15, 30, 60, 120, 240)


def net_return_pct(
    gross_return_pct: float,
    *,
    fee_rate: float = FEE_RATE,
    slip_bps: float = SLIP_BPS_DEFAULT,
) -> float:
    """% return after round-trip fee + slippage (approx on notional)."""

    fee_pct = fee_rate * 2 * 100.0  # both sides in %
    slip_pct = (slip_bps / 10000.0) * 2 * 100.0
    return float(gross_return_pct) - fee_pct - slip_pct


def net_pnl_krw(net_ret_pct: float, notional: float = NOTIONAL) -> float:
    return notional * (net_ret_pct / 100.0)


def summarize_nets(
    nets: Sequence[float],
    *,
    days: float,
    regimes: Sequence[str] | None = None,
) -> dict[str, Any]:
    xs = [float(x) for x in nets]
    n = len(xs)
    if n == 0:
        return {
            "n": 0,
            "opportunities_day": 0.0,
            "trades_day": 0.0,
            "win_rate": None,
            "pf": None,
            "avg_net_trade": None,
            "median_net_trade": None,
            "total_net": 0.0,
            "mdd": 0.0,
            "best_regime": None,
            "confidence": confidence_from_n(0),
        }
    wins = sum(1 for x in xs if x > 0)
    best_reg = None
    if regimes and len(regimes) == n:
        by: dict[str, list[float]] = {}
        for r, x in zip(regimes, xs):
            by.setdefault(str(r), []).append(x)
        best_reg = max(
            by.items(),
            key=lambda kv: sum(kv[1]) / max(len(kv[1]), 1),
        )[0]
    d = max(float(days), 1.0)
    return {
        "n": n,
        "opportunities_day": round(n / d, 2),
        "trades_day": round(n / d, 2),
        "win_rate": round(100.0 * wins / n, 1),
        "pf": round(profit_factor(xs), 3),
        "avg_net_trade": round(statistics.fmean(xs), 2),
        "median_net_trade": round(float(statistics.median(xs)), 2),
        "total_net": round(sum(xs), 1),
        "mdd": round(max_drawdown(xs), 1),
        "best_regime": best_reg,
        "confidence": confidence_from_n(n),
    }


def promotion_ok(summary: dict[str, Any]) -> bool:
    """MINIMUM PROMOTION CRITERIA (TEST)."""

    n = int(summary.get("n") or 0)
    pf = summary.get("pf")
    total = float(summary.get("total_net") or 0)
    if n < 30:
        return False
    if pf is None or float(pf) < 1.1:
        return False
    if total <= 0:
        return False
    return True
