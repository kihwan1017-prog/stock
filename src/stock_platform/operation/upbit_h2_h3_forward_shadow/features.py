"""Feature helpers for frozen H2/H3 — same formulas as WRK-018."""

from __future__ import annotations

from typing import Sequence


def sma(closes: Sequence[float], end: int, window: int) -> float | None:
    if end + 1 < window or window <= 0:
        return None
    chunk = closes[end - window + 1 : end + 1]
    return sum(chunk) / float(window)


def ret_pct(closes: Sequence[float], end: int, lookback: int) -> float | None:
    j = end - lookback
    if j < 0 or closes[j] <= 0 or closes[end] <= 0:
        return None
    return (closes[end] / closes[j] - 1.0) * 100.0


def features_at(
    *,
    closes: Sequence[float],
    lows: Sequence[float],
    idx: int,
) -> dict[str, float] | None:
    """Compute H2/H3 features at idx using only data <= idx."""

    if idx < 20 or idx >= len(closes):
        return None
    ma20 = sma(closes, idx, 20)
    if ma20 is None or ma20 <= 0:
        return None
    entry = float(closes[idx])
    r1 = ret_pct(closes, idx, 1)
    if r1 is None:
        return None
    prior_low = min(lows[idx - 20 : idx]) if idx >= 20 else float(lows[idx])
    if prior_low <= 0:
        return None
    return {
        "dist_ma20_pct": (entry / ma20 - 1.0) * 100.0,
        "ret_1m": float(r1),
        "dist_low_20_pct": (entry / prior_low - 1.0) * 100.0,
        "close": entry,
    }
