"""STEP 11-13 — Fingerprint-only revalidation (no AI)."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.candidate_lifecycle.fingerprint import (
    compute_fingerprint,
    fingerprints_match,
)
from stock_platform.ai.candidate_lifecycle.provenance import build_combined_fingerprint


def build_current_fingerprint(source_graph: dict[str, Any]) -> str:
    """현재 provenance source_graph 기준 fingerprint."""
    return build_combined_fingerprint(source_graph)


def compare_fingerprints(
    *,
    expected: str | None,
    actual: str | None,
) -> dict[str, Any]:
    """Fingerprint 비교 결과 (AI 호출 없음)."""
    matched = fingerprints_match(expected, actual)
    warnings: list[str] = []
    if not expected:
        warnings.append("EXPECTED_FINGERPRINT_MISSING")
    if not actual:
        warnings.append("ACTUAL_FINGERPRINT_MISSING")
    if expected and actual and not matched:
        warnings.append("FINGERPRINT_MISMATCH")

    if matched and not warnings:
        status = "PASSED"
    elif matched and warnings:
        status = "PASSED_WITH_WARNING"
    else:
        status = "FAILED"

    return {
        "matched": matched,
        "status": status,
        "expected_fingerprint": expected,
        "actual_fingerprint": actual,
        "warnings": warnings,
    }


def revalidation_outcome_from_fields(
    *,
    stored_fields: dict[str, Any],
    current_fields: dict[str, Any],
) -> dict[str, Any]:
    """필드 dict 두 세트를 fingerprint로 비교."""
    expected = compute_fingerprint(stored_fields)
    actual = compute_fingerprint(current_fields)
    return compare_fingerprints(expected=expected, actual=actual)
