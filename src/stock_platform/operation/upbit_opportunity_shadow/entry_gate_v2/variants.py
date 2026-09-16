"""V2 decision variants — HARD safety vs QUALITY filters (LIVE E0 불변)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.constants import (
    DEFAULT_MAX_GC_AGE_MIN,
    DEFAULT_MAX_PRE5,
    DEFAULT_MAX_RANGE,
    DEFAULT_SCORE_MIN,
    DEFAULT_SCORE_MIN_BULL,
    DEFAULT_SCORE_MIN_SIDE,
    V2_A,
    V2_C,
    V2_D,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.features import (
    V2Features,
    quality_score,
)


@dataclass(frozen=True, slots=True)
class V2Decision:
    variant: str
    allow: bool
    block_reason: str | None
    score: float
    hard_block: bool


def _hard_block(feat: V2Features) -> str | None:
    if feat.ma_gap_pct is None and feat.pre5 is None:
        return "INSUFFICIENT_FEATURES"
    return None


def decide_v2_a(feat: V2Features, *, score_min: float = DEFAULT_SCORE_MIN) -> V2Decision:
    hb = _hard_block(feat)
    s = quality_score(feat)
    if hb:
        return V2Decision(V2_A, False, hb, s, True)
    if feat.ma_gap_pct is not None and feat.ma_gap_pct <= 0:
        return V2Decision(V2_A, False, "TREND_NOT_POSITIVE", s, False)
    if s < score_min:
        return V2Decision(V2_A, False, "QUALITY_SCORE_TOO_LOW", s, False)
    return V2Decision(V2_A, True, None, s, False)


def decide_v2_c(
    feat: V2Features,
    *,
    max_gc_age: float = DEFAULT_MAX_GC_AGE_MIN,
    max_pre5: float = DEFAULT_MAX_PRE5,
    max_range: float = DEFAULT_MAX_RANGE,
) -> V2Decision:
    hb = _hard_block(feat)
    s = quality_score(feat)
    if hb:
        return V2Decision(V2_C, False, hb, s, True)
    if feat.ma_gap_pct is None or feat.ma_gap_pct <= 0:
        return V2Decision(V2_C, False, "SHORT_MA_NOT_ABOVE_LONG_MA", s, False)
    if feat.gc_age_min is None or feat.gc_age_min > max_gc_age:
        return V2Decision(V2_C, False, "GOLDEN_CROSS_STALE", s, False)
    if feat.pre5 is not None and feat.pre5 > max_pre5:
        return V2Decision(V2_C, False, "CHASE_PRE5_TOO_HIGH", s, False)
    if feat.range_pos15 is not None and feat.range_pos15 > max_range:
        return V2Decision(V2_C, False, "CHASE_RANGE_POS_TOO_HIGH", s, False)
    return V2Decision(V2_C, True, None, s, False)


def decide_v2_d(
    feat: V2Features,
    *,
    score_min: float = DEFAULT_SCORE_MIN,
    score_min_bull: float = DEFAULT_SCORE_MIN_BULL,
    score_min_side: float = DEFAULT_SCORE_MIN_SIDE,
    max_gc_age: float = DEFAULT_MAX_GC_AGE_MIN,
    max_pre5: float = DEFAULT_MAX_PRE5,
    max_range: float = DEFAULT_MAX_RANGE,
) -> V2Decision:
    hb = _hard_block(feat)
    s = quality_score(feat)
    if hb:
        return V2Decision(V2_D, False, hb, s, True)
    if feat.regime == "BEARISH":
        return V2Decision(V2_D, False, "REGIME_BEARISH", s, False)
    need = score_min_bull if feat.regime == "BULLISH" else score_min_side
    need = max(need, score_min)
    if feat.ma_gap_pct is None or feat.ma_gap_pct <= 0:
        return V2Decision(V2_D, False, "TREND_NOT_POSITIVE", s, False)
    if s < need:
        return V2Decision(V2_D, False, "QUALITY_SCORE_TOO_LOW", s, False)
    if feat.gc_age_min is not None and feat.gc_age_min > max_gc_age:
        return V2Decision(V2_D, False, "GOLDEN_CROSS_STALE", s, False)
    if feat.pre5 is not None and feat.pre5 > max_pre5:
        return V2Decision(V2_D, False, "CHASE_PRE5_TOO_HIGH", s, False)
    if feat.range_pos15 is not None and feat.range_pos15 > max_range:
        return V2Decision(V2_D, False, "CHASE_RANGE_POS_TOO_HIGH", s, False)
    return V2Decision(V2_D, True, None, s, False)


def evaluate_all_v2(feat: V2Features) -> dict[str, dict[str, Any]]:
    decisions = (
        decide_v2_a(feat),
        decide_v2_c(feat),
        decide_v2_d(feat),
    )
    return {
        d.variant: {
            "allow": d.allow,
            "block_reason": d.block_reason,
            "score": d.score,
            "hard_block": d.hard_block,
        }
        for d in decisions
    }
