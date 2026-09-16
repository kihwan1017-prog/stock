"""WRK-018 helpers — effect size, bins, concentration."""

from __future__ import annotations

import math
from typing import Sequence


def effect_size(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Cohen's d (group A mean - group B mean)."""

    if len(a) < 5 or len(b) < 5:
        return None
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / max(len(a) - 1, 1)
    vb = sum((y - mb) ** 2 for y in b) / max(len(b) - 1, 1)
    pooled = math.sqrt((va + vb) / 2.0)
    if pooled <= 1e-12:
        return 0.0
    return (ma - mb) / pooled


def quintile_edges(xs: Sequence[float]) -> list[float] | None:
    if len(xs) < 25:
        return None
    ordered = sorted(float(x) for x in xs)
    n = len(ordered)

    def q(p: float) -> float:
        i = min(n - 1, max(0, int(round((n - 1) * p))))
        return ordered[i]

    return [q(0.2), q(0.4), q(0.6), q(0.8)]


def assign_quintile(x: float, edges: Sequence[float]) -> int:
    for i, e in enumerate(edges):
        if x <= e:
            return i + 1
    return 5


def profit_concentration(nets: Sequence[float]) -> dict[str, float]:
    wins = sorted([n for n in nets if n > 0], reverse=True)
    total = sum(wins)
    if total <= 0 or not wins:
        return {"top1": 0.0, "top2": 0.0, "top5": 0.0, "top10": 0.0}
    return {
        "top1": round(wins[0] / total, 3),
        "top2": round(sum(wins[:2]) / total, 3),
        "top5": round(sum(wins[:5]) / total, 3),
        "top10": round(sum(wins[:10]) / total, 3),
    }


def period_bucket(frac: float) -> str:
    if frac < 1.0 / 3.0:
        return "EARLY"
    if frac < 2.0 / 3.0:
        return "MIDDLE"
    return "LATE"
