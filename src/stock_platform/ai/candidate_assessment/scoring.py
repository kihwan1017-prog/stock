"""STEP 11-9 — 점수·Confidence·금지 필드 검증."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.candidate_assessment.constants import (
    CONFLICT_STATUS,
    FORBIDDEN_RESULT_KEYS,
    MAX_CONFIDENCE_MAJOR_CONFLICT,
    MAX_CONFIDENCE_METADATA_ONLY,
    MAX_CONFIDENCE_NO_REVIEW,
    MAX_CONFIDENCE_STALE,
    SCORE_MAX,
    SCORE_MIN,
    TEMPORAL_STATUS,
)


def clamp_score(value: float | int | None) -> float:
    """0~100 점수 클램프."""

    if value is None:
        return float(SCORE_MIN)
    try:
        num = float(value)
    except (TypeError, ValueError):
        return float(SCORE_MIN)
    return max(float(SCORE_MIN), min(float(SCORE_MAX), num))


def compute_analytical_score(sub_scores: dict[str, float | int | None]) -> float:
    """하위 점수 가중 합산 — 서버 측 analytical_score."""

    weights = {
        "news_score": 0.20,
        "disclosure_score": 0.15,
        "chart_score": 0.25,
        "market_score": 0.20,
        "evidence_quality_score": 0.10,
        "uncertainty_score": 0.10,
    }
    total_weight = 0.0
    weighted = 0.0
    for key, weight in weights.items():
        if key in sub_scores and sub_scores[key] is not None:
            weighted += clamp_score(sub_scores[key]) * weight
            total_weight += weight
    if total_weight <= 0:
        fallback = sub_scores.get("analytical_score")
        return clamp_score(fallback if fallback is not None else SCORE_MIN)
    return clamp_score(weighted / total_weight)


def apply_confidence_caps(
    raw_confidence: float | None,
    *,
    has_review: bool,
    conflict_status: str | None,
    temporal_status: str | None,
    metadata_only: bool,
) -> float:
    """Evidence·Review·충돌·시간 정합성에 따른 confidence 상한."""

    try:
        conf = float(raw_confidence) if raw_confidence is not None else 0.5
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))

    cap = 1.0
    if not has_review:
        cap = min(cap, MAX_CONFIDENCE_NO_REVIEW)
    if metadata_only:
        cap = min(cap, MAX_CONFIDENCE_METADATA_ONLY)
    if conflict_status == "MAJOR_CONFLICT":
        cap = min(cap, MAX_CONFIDENCE_MAJOR_CONFLICT)
    if temporal_status in {"STALE", "CONFLICTED"}:
        cap = min(cap, MAX_CONFIDENCE_STALE)

    return round(min(conf, cap), 4)


def strip_forbidden_fields(
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """금지 필드 제거 및 위반 목록 반환."""

    if not payload:
        return {}, []
    violations: list[str] = []
    cleaned: dict[str, Any] = {}

    def _walk(obj: Any, path: str = "") -> Any:
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for key, value in obj.items():
                full = f"{path}.{key}" if path else str(key)
                if str(key).lower() in FORBIDDEN_RESULT_KEYS:
                    violations.append(full)
                    continue
                out[key] = _walk(value, full)
            return out
        if isinstance(obj, list):
            return [_walk(item, path) for item in obj]
        return obj

    cleaned = _walk(payload)
    if not isinstance(cleaned, dict):
        cleaned = {}
    return cleaned, violations


def validate_result_payload(
    payload: dict[str, Any] | None,
    task_type: str,
) -> list[str]:
    """결과 payload 스키마·금지 필드 검증 findings."""

    findings: list[str] = []
    if not payload:
        findings.append("EMPTY_PAYLOAD")
        return findings

    _, violations = strip_forbidden_fields(payload)
    findings.extend([f"FORBIDDEN_FIELD:{v}" for v in violations])

    result_body = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if isinstance(result_body, dict):
        _, inner_violations = strip_forbidden_fields(result_body)
        findings.extend([f"FORBIDDEN_FIELD:result.{v}" for v in inner_violations])

    expected_task = task_type
    body_task = None
    if isinstance(result_body, dict):
        body_task = result_body.get("task_type")
    if body_task and body_task != expected_task:
        findings.append("TASK_TYPE_MISMATCH")

    for score_key in ("analytical_score", "risk_score"):
        val = None
        if isinstance(result_body, dict):
            val = result_body.get(score_key)
        if val is not None:
            try:
                num = float(val)
                if num < SCORE_MIN or num > SCORE_MAX:
                    findings.append(f"SCORE_OUT_OF_RANGE:{score_key}")
            except (TypeError, ValueError):
                findings.append(f"SCORE_INVALID:{score_key}")

    conf = None
    if isinstance(result_body, dict):
        conf = result_body.get("confidence")
    if conf is not None:
        try:
            c = float(conf)
            if c < 0 or c > 1:
                findings.append("CONFIDENCE_OUT_OF_RANGE")
        except (TypeError, ValueError):
            findings.append("CONFIDENCE_INVALID")

    cs = None
    if isinstance(result_body, dict):
        cs = result_body.get("conflict_status")
    if cs and cs not in CONFLICT_STATUS:
        findings.append("INVALID_CONFLICT_STATUS")

    ts = None
    if isinstance(result_body, dict):
        ts = result_body.get("temporal_alignment_status")
    if ts and ts not in TEMPORAL_STATUS:
        findings.append("INVALID_TEMPORAL_STATUS")

    return findings
