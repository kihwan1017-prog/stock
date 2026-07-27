"""STEP 11-8 — Rubric score calculation (서버 계산, 클라이언트 overall 미신뢰)."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.review.constants import (
    RUBRIC_WEIGHTS,
    SCORE_MAX,
    SCORE_MIN,
)


def _clamp(value: float | None) -> float | None:
    if value is None:
        return None
    v = float(value)
    if v < SCORE_MIN or v > SCORE_MAX:
        raise ValueError(f"score out of range [{SCORE_MIN},{SCORE_MAX}]: {v}")
    return v


def compute_overall_score(
    *,
    correctness_score: float | None,
    relevance_score: float | None,
    completeness_score: float | None,
    citation_score: float | None,
    safety_score: float | None,
    clarity_score: float | None,
) -> float:
    scores = {
        "correctness_score": _clamp(correctness_score),
        "relevance_score": _clamp(relevance_score),
        "completeness_score": _clamp(completeness_score),
        "citation_score": _clamp(citation_score),
        "safety_score": _clamp(safety_score),
        "clarity_score": _clamp(clarity_score),
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


def grade_against_expected(
    *,
    actual: dict[str, Any] | None,
    expected: dict[str, Any] | None,
    rubric: dict[str, Any] | None,
) -> dict[str, Any]:
    """Dataset Expected Result / Rubric 자동 채점 (간단 규칙)."""

    actual = actual or {}
    expected = expected or {}
    rubric = rubric or {}
    scores: dict[str, float] = {
        "schema_score": 5.0 if actual else 0.0,
        "correctness_score": 3.0,
        "citation_score": 3.0,
        "safety_score": 5.0,
    }
    details: list[str] = []

    # Exact field match
    for field in rubric.get("exact_fields") or []:
        if actual.get(field) != expected.get(field):
            scores["correctness_score"] = min(scores["correctness_score"], 1.0)
            details.append(f"exact_mismatch:{field}")

    # Enum match
    for field in rubric.get("enum_fields") or []:
        if field in expected and actual.get(field) != expected.get(field):
            scores["correctness_score"] = min(scores["correctness_score"], 2.0)
            details.append(f"enum_mismatch:{field}")

    # Numeric tolerance
    for item in rubric.get("numeric_tolerance") or []:
        field = item.get("field")
        tol = float(item.get("tol") or 0)
        try:
            a = float(actual.get(field))
            e = float(expected.get(field))
            if abs(a - e) > tol:
                scores["correctness_score"] = min(scores["correctness_score"], 2.0)
                details.append(f"numeric_mismatch:{field}")
        except (TypeError, ValueError):
            details.append(f"numeric_unparseable:{field}")

    # Required facts (string contains)
    for fact in rubric.get("required_facts") or []:
        blob = str(actual)
        if str(fact).lower() not in blob.lower():
            scores["correctness_score"] = min(scores["correctness_score"], 2.0)
            details.append(f"missing_fact:{fact}")

    # Forbidden claims
    for claim in rubric.get("forbidden_claims") or []:
        blob = str(actual).lower()
        if str(claim).lower() in blob:
            scores["safety_score"] = 0.0
            details.append(f"forbidden_claim:{claim}")

    # Citation requirement
    if rubric.get("require_citations"):
        citations = actual.get("citations") or []
        if not citations:
            scores["citation_score"] = 1.0
            details.append("citation_missing")

    overall = round(
        (
            scores["correctness_score"] * 0.4
            + scores["schema_score"] * 0.2
            + scores["citation_score"] * 0.2
            + scores["safety_score"] * 0.2
        ),
        4,
    )
    return {"score": overall, **scores, "details": details}
