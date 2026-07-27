"""STEP 11-11 — Promotion eligibility snapshot (등록/승격 실행 없음)."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.candidate_recommendation_queue.constants import (
    CONSIDERATION_LABEL,
    MIN_OVERALL_FOR_CONSIDERATION,
    MIN_SAFETY_FOR_CONSIDERATION,
    REFERENCE_DISCLAIMER,
)


def build_promotion_eligibility_snapshot(
    *,
    queue_status: str,
    latest_decision: str | None,
    submitted_reviews: list[dict[str, Any]],
    critical_findings_count: int,
    unresolved_high_findings_count: int,
    stale: bool,
    expired: bool,
    existing_candidate_conflict: bool,
) -> dict[str, Any]:
    """
    후속 승격(별도 STEP) 가능성 스냅샷.

    Safety: APPROVED_FOR_CONSIDERATION ≠ strategy.candidate 등록.
    이 함수는 스냅샷만 반환하며 INSERT/UPDATE/trading side-effect 없음.
    """
    blockers: list[str] = []
    warnings: list[str] = []

    if queue_status != "APPROVED_FOR_CONSIDERATION":
        blockers.append(f"QUEUE_STATUS_{queue_status}")
    if latest_decision != "APPROVED_FOR_CONSIDERATION":
        blockers.append(f"DECISION_{latest_decision or 'NONE'}")
    if critical_findings_count > 0:
        blockers.append("CRITICAL_FINDINGS_PRESENT")
    if unresolved_high_findings_count > 0:
        blockers.append("UNRESOLVED_HIGH_FINDINGS")
    if stale:
        blockers.append("SOURCE_STALE")
    if expired:
        blockers.append("QUEUE_EXPIRED")
    if existing_candidate_conflict:
        warnings.append("EXISTING_CANDIDATE_CONFLICT")

    overalls = [
        float(r["overall_score"])
        for r in submitted_reviews
        if r.get("overall_score") is not None
    ]
    safeties = [
        float(r["safety_score"])
        for r in submitted_reviews
        if r.get("safety_score") is not None
    ]
    avg_overall = round(sum(overalls) / len(overalls), 4) if overalls else None
    avg_safety = round(sum(safeties) / len(safeties), 4) if safeties else None

    if avg_overall is not None and avg_overall < MIN_OVERALL_FOR_CONSIDERATION:
        warnings.append("BELOW_MIN_OVERALL")
    if avg_safety is not None and avg_safety < MIN_SAFETY_FOR_CONSIDERATION:
        warnings.append("BELOW_MIN_SAFETY")

    eligible_for_future_promotion = len(blockers) == 0

    return {
        "eligible_for_future_promotion": eligible_for_future_promotion,
        "blockers": blockers,
        "warnings": warnings,
        "average_overall_score": avg_overall,
        "average_safety_score": avg_safety,
        "reviewer_count": len(submitted_reviews),
        "consideration_label": CONSIDERATION_LABEL,
        "disclaimer": REFERENCE_DISCLAIMER,
        "note": (
            "APPROVED_FOR_CONSIDERATION is review workflow outcome only; "
            "does NOT register strategy.candidate or trigger trading."
        ),
    }
