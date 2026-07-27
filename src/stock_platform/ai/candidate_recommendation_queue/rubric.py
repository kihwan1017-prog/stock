"""STEP 11-11 — Review rubric (서버 계산, 클라이언트 overall 미신뢰)."""

from __future__ import annotations

from stock_platform.ai.candidate_recommendation_queue.constants import (
    RUBRIC_MAX,
    RUBRIC_MIN,
    RUBRIC_WEIGHTS,
)


def _clamp(value: float | None) -> float | None:
    if value is None:
        return None
    v = float(value)
    if v < RUBRIC_MIN or v > RUBRIC_MAX:
        raise ValueError(f"score out of range [{RUBRIC_MIN},{RUBRIC_MAX}]: {v}")
    return v


def compute_overall_score(
    *,
    eligibility_score: float | None,
    analytical_quality_score: float | None,
    evidence_quality_score: float | None,
    risk_awareness_score: float | None,
    consistency_score: float | None,
    safety_score: float | None,
) -> float:
    scores = {
        "eligibility_score": _clamp(eligibility_score),
        "analytical_quality_score": _clamp(analytical_quality_score),
        "evidence_quality_score": _clamp(evidence_quality_score),
        "risk_awareness_score": _clamp(risk_awareness_score),
        "consistency_score": _clamp(consistency_score),
        "safety_score": _clamp(safety_score),
    }
    missing = [k for k, v in scores.items() if v is None]
    if missing:
        raise ValueError(f"missing required rubric scores: {missing}")
    total = 0.0
    for key, weight in RUBRIC_WEIGHTS.items():
        total += float(scores[key]) * weight
    return round(total, 4)


def validate_optional_score(value: float | None) -> float | None:
    return _clamp(value)
