"""STEP 11-12 — Promotion Candidate Score (서버 산식, AI confidence 단독 사용 금지)."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.candidate_promotion.constants import (
    CONFIDENCE_CONTRIBUTION_CAP,
    RUBRIC_SCALE_MAX,
    SCORE_FORMULA_VERSION,
    SCORE_SOURCE_TYPE,
)


def clamp_0_100(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 2)


def _agreement_factor(agreement_level: str | None) -> float:
    level = (agreement_level or "").upper()
    mapping = {
        "HIGH": 1.0,
        "STRONG": 1.0,
        "MODERATE": 0.75,
        "MEDIUM": 0.65,
        "LOW": 0.40,
        "LIMITED": 0.30,
        "WEAK": 0.25,
    }
    return mapping.get(level, 0.50)


def _evidence_factor(
    *,
    source_quality_score: float | None,
    evidence_quality: str | None = None,
) -> float:
    if source_quality_score is not None:
        # source_quality_score는 assessment overall 0~100 또는 rubric — 정규화
        val = float(source_quality_score)
        if val <= RUBRIC_SCALE_MAX:
            return clamp_0_100(val / RUBRIC_SCALE_MAX * 100) / 100.0
        return clamp_0_100(val) / 100.0
    quality = (evidence_quality or "").upper()
    quality_map = {
        "HIGH": 0.90,
        "GOOD": 0.80,
        "MODERATE": 0.65,
        "LOW": 0.45,
        "POOR": 0.30,
    }
    return quality_map.get(quality, 0.55)


def compute_promotion_score(
    *,
    review_overall_scores: list[float],
    source_quality_score: float | None,
    confidence: float | None,
    agreement_level: str | None,
    risk_score: float | None,
    warning_count: int = 0,
    has_critical: bool = False,
) -> dict[str, Any]:
    """
    promotion_candidate_score = clamp_0_100(
      review_overall_norm * 40
      + evidence_factor * 20
      + confidence_capped * 15
      + agreement_factor * 15
      - risk_penalty * 20
      - warning_penalty * 10
    )

    AI analytical_score/confidence를 total_score로 직접 복사하지 않는다.
    """
    if has_critical:
        return {
            "total_score": 0.0,
            "source_type": SCORE_SOURCE_TYPE,
            "formula_version": SCORE_FORMULA_VERSION,
            "components": {
                "blocked": True,
                "reason": "CRITICAL_FINDINGS",
            },
        }

    if review_overall_scores:
        avg_review = sum(review_overall_scores) / len(review_overall_scores)
        review_overall_norm = min(avg_review / RUBRIC_SCALE_MAX, 1.0)
    else:
        review_overall_norm = 0.5

    evidence_factor = _evidence_factor(source_quality_score=source_quality_score)

    raw_confidence = float(confidence or 0.0)
    if raw_confidence > 1.0:
        raw_confidence = raw_confidence / 100.0
    confidence_capped = min(raw_confidence, CONFIDENCE_CONTRIBUTION_CAP)

    agreement_factor = _agreement_factor(agreement_level)

    risk_val = float(risk_score or 0.0)
    if risk_val > 1.0:
        risk_val = risk_val / 100.0
    risk_penalty = min(max(risk_val, 0.0), 1.0)

    warning_penalty = min(max(warning_count, 0) * 0.15, 1.0)

    raw_score = (
        review_overall_norm * 40.0
        + evidence_factor * 20.0
        + confidence_capped * 15.0
        + agreement_factor * 15.0
        - risk_penalty * 20.0
        - warning_penalty * 10.0
    )
    total_score = clamp_0_100(raw_score)

    return {
        "total_score": total_score,
        "source_type": SCORE_SOURCE_TYPE,
        "formula_version": SCORE_FORMULA_VERSION,
        "components": {
            "review_overall_norm": round(review_overall_norm, 4),
            "evidence_factor": round(evidence_factor, 4),
            "confidence_capped": round(confidence_capped, 4),
            "agreement_factor": round(agreement_factor, 4),
            "risk_penalty": round(risk_penalty, 4),
            "warning_penalty": round(warning_penalty, 4),
            "raw_score_before_clamp": round(raw_score, 4),
        },
    }
