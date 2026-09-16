"""STEP N6 — deterministic scoring (LLM 금지)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stock_platform.operation.upbit_news_combined_shadow.policy import (
    DECISION_BOOST,
    DECISION_DEPRIORITIZE,
    DECISION_THRESHOLD,
    DECISION_UNCHANGED,
    DIRECTION_VALUE,
    NEWS_COMPONENT_CLAMP,
    NEWS_SCORE_MAX_ADJUSTMENT,
    RECENCY_BUCKETS,
    RELIABILITY_WEIGHT,
    STRENGTH_WEIGHT,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def direction_value(direction: str) -> float:
    return float(DIRECTION_VALUE.get(str(direction or "").upper(), 0.0))


def strength_weight(strength: str) -> float:
    return float(STRENGTH_WEIGHT.get(str(strength or "").upper(), 0.5))


def reliability_weight(reliability: str) -> float:
    return float(RELIABILITY_WEIGHT.get(str(reliability or "").upper(), 0.25))


def recency_weight(*, published_at: datetime, t0: datetime) -> float:
    age = (_as_utc(t0) - _as_utc(published_at)).total_seconds()
    if age < 0:
        return 0.0
    for max_age, weight in RECENCY_BUCKETS:
        if age <= max_age:
            return float(weight)
    return 0.0


def signal_contribution(
    *,
    direction: str,
    strength: str,
    reliability: str,
    published_at: datetime,
    t0: datetime,
    influence_allowed: bool,
) -> dict[str, Any]:
    if not influence_allowed:
        return {
            "contribution": 0.0,
            "direction_value": direction_value(direction),
            "strength_weight": strength_weight(strength),
            "reliability_weight": reliability_weight(reliability),
            "recency_weight": 0.0,
            "influence_allowed": False,
        }
    d = direction_value(direction)
    sw = strength_weight(strength)
    rw = reliability_weight(reliability)
    rw_age = recency_weight(published_at=published_at, t0=t0)
    contrib = d * sw * rw * rw_age
    # 개별 대략 -1.5 ~ +1.5
    contrib = max(-1.5, min(1.5, contrib))
    return {
        "contribution": round(contrib, 6),
        "direction_value": d,
        "strength_weight": sw,
        "reliability_weight": rw,
        "recency_weight": rw_age,
        "influence_allowed": True,
    }


def aggregate_news_component(contributions: list[float]) -> dict[str, float]:
    raw = float(sum(contributions))
    clamped = max(-NEWS_COMPONENT_CLAMP, min(NEWS_COMPONENT_CLAMP, raw))
    normalized = clamped / NEWS_COMPONENT_CLAMP
    return {
        "raw_news_component": round(raw, 6),
        "experimental_news_component": round(clamped, 6),
        "news_component_normalized": round(normalized, 6),
    }


def experimental_combined_score(
    *,
    scanner_score: float,
    news_component_normalized: float,
) -> float:
    score = float(scanner_score) + (
        float(news_component_normalized) * NEWS_SCORE_MAX_ADJUSTMENT
    )
    return round(max(0.0, min(100.0, score)), 6)


def experimental_decision(news_component_normalized: float) -> str:
    n = float(news_component_normalized)
    if n >= DECISION_THRESHOLD:
        return DECISION_BOOST
    if n <= -DECISION_THRESHOLD:
        return DECISION_DEPRIORITIZE
    return DECISION_UNCHANGED


def assign_counterfactual_ranks(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """동일 run 내 experimental_combined_score 내림차순 rank (1-based)."""

    ordered = sorted(
        rows,
        key=lambda r: (
            -float(r.get("experimental_combined_score") or 0),
            int(r.get("control_scanner_rank") or 10_000),
            str(r.get("symbol") or ""),
        ),
    )
    for idx, row in enumerate(ordered, start=1):
        row["counterfactual_rank"] = idx
        actual = int(row.get("control_scanner_rank") or 0)
        row["rank_delta"] = (
            (actual - idx) if actual > 0 else None
        )  # +면 실험상 상승
    return ordered
