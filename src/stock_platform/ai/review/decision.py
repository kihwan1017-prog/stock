"""STEP 11-8 — Final Decision 규칙 (Core Safety 해제 불가)."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.review.constants import (
    MAJOR_DISAGREEMENT_SPREAD,
    MIN_AVG_OVERALL_APPROVE,
    MIN_AVG_SAFETY_APPROVE,
    MIN_REVIEWERS_FOR_APPROVE,
)


def compute_consensus(overall_scores: list[float]) -> str:
    if len(overall_scores) < MIN_REVIEWERS_FOR_APPROVE:
        return "INSUFFICIENT_REVIEWS"
    if len(overall_scores) == 1:
        return "CONSENSUS"
    spread = max(overall_scores) - min(overall_scores)
    if spread >= MAJOR_DISAGREEMENT_SPREAD:
        return "MAJOR_DISAGREEMENT"
    if spread >= 1.0:
        return "MINOR_DISAGREEMENT"
    return "CONSENSUS"


def calculate_decision(
    *,
    submitted_reviews: list[dict[str, Any]],
    critical_finding_count: int,
    source_status: str | None = None,
) -> dict[str, Any]:
    """
    submitted_reviews: decision, overall_score, safety_score
    """

    if source_status in {"BLOCKED", "INVALID", "FAILED"}:
        # Failure Review는 별도 — 기본은 NOT_REVIEWABLE for approve path
        pass

    if not submitted_reviews:
        return {
            "decision": "PENDING",
            "consensus_status": "INSUFFICIENT_REVIEWS",
            "decision_rule": "AUTO",
            "reviewer_count": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "warning_count": 0,
            "average_overall_score": None,
            "critical_finding_count": critical_finding_count,
        }

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
    decisions = [str(r.get("decision") or "PENDING") for r in submitted_reviews]
    approved = sum(
        1
        for d in decisions
        if d in {"APPROVED", "APPROVED_WITH_WARNINGS"}
    )
    rejected = sum(1 for d in decisions if d == "REJECTED")
    warnings = sum(1 for d in decisions if d == "APPROVED_WITH_WARNINGS")
    revision = sum(1 for d in decisions if d == "REVISION_REQUESTED")
    avg_overall = round(sum(overalls) / len(overalls), 4) if overalls else None
    avg_safety = round(sum(safeties) / len(safeties), 4) if safeties else None
    consensus = compute_consensus(overalls)

    # Core Safety: Critical Finding → APPROVED 금지
    if critical_finding_count > 0:
        return {
            "decision": "REJECTED",
            "consensus_status": consensus,
            "decision_rule": "CORE_SAFETY_CRITICAL",
            "reviewer_count": len(submitted_reviews),
            "approved_count": approved,
            "rejected_count": max(rejected, 1),
            "warning_count": warnings,
            "average_overall_score": avg_overall,
            "critical_finding_count": critical_finding_count,
        }

    if consensus == "MAJOR_DISAGREEMENT":
        return {
            "decision": "PENDING",
            "consensus_status": "MANAGER_REVIEW_REQUIRED",
            "decision_rule": "MAJOR_DISAGREEMENT",
            "reviewer_count": len(submitted_reviews),
            "approved_count": approved,
            "rejected_count": rejected,
            "warning_count": warnings,
            "average_overall_score": avg_overall,
            "critical_finding_count": 0,
        }

    if rejected > approved:
        return {
            "decision": "REJECTED",
            "consensus_status": consensus,
            "decision_rule": "MAJORITY_REJECT",
            "reviewer_count": len(submitted_reviews),
            "approved_count": approved,
            "rejected_count": rejected,
            "warning_count": warnings,
            "average_overall_score": avg_overall,
            "critical_finding_count": 0,
        }

    if revision and not approved:
        return {
            "decision": "REVISION_REQUESTED",
            "consensus_status": consensus,
            "decision_rule": "REVISION_REQUESTED",
            "reviewer_count": len(submitted_reviews),
            "approved_count": approved,
            "rejected_count": rejected,
            "warning_count": warnings,
            "average_overall_score": avg_overall,
            "critical_finding_count": 0,
        }

    if (
        len(submitted_reviews) >= MIN_REVIEWERS_FOR_APPROVE
        and avg_overall is not None
        and avg_overall >= MIN_AVG_OVERALL_APPROVE
        and avg_safety is not None
        and avg_safety >= MIN_AVG_SAFETY_APPROVE
        and approved > 0
    ):
        decision = (
            "APPROVED_WITH_WARNINGS" if warnings or revision else "APPROVED"
        )
        return {
            "decision": decision,
            "consensus_status": consensus,
            "decision_rule": "AUTO_THRESHOLD",
            "reviewer_count": len(submitted_reviews),
            "approved_count": approved,
            "rejected_count": rejected,
            "warning_count": warnings,
            "average_overall_score": avg_overall,
            "critical_finding_count": 0,
        }

    return {
        "decision": "PENDING",
        "consensus_status": consensus,
        "decision_rule": "AWAITING_THRESHOLD",
        "reviewer_count": len(submitted_reviews),
        "approved_count": approved,
        "rejected_count": rejected,
        "warning_count": warnings,
        "average_overall_score": avg_overall,
        "critical_finding_count": 0,
    }
