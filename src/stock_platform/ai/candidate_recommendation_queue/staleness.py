"""STEP 11-11 — Source staleness detection (hash mismatch)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.candidate_recommendation_queue.eligibility import (
    AIRecommendationQueueEligibilityService,
)


class AIRecommendationQueueStalenessService:
    """큐 생성 이후 소스 result_hash/evidence 변경 여부 확인."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._eligibility = AIRecommendationQueueEligibilityService(session)

    def check(
        self,
        *,
        source_type: str,
        candidate_assessment_id: int | None,
        candidate_consensus_id: int | None,
        stored_source_result_hash: str,
        stored_evidence_bundle_hash: str | None,
    ) -> dict[str, Any]:
        current = self._eligibility.validate_source(
            source_type=source_type,
            candidate_assessment_id=candidate_assessment_id,
            candidate_consensus_id=candidate_consensus_id,
            allow_existing_candidate_override=True,
            override_reason="staleness_check",
        )
        snapshot = current.get("snapshot") or {}
        stale_reasons: list[str] = []

        current_hash = snapshot.get("source_result_hash") or ""
        if current_hash != stored_source_result_hash:
            stale_reasons.append("SOURCE_RESULT_HASH_CHANGED")

        current_evidence = snapshot.get("evidence_bundle_hash")
        if (
            stored_evidence_bundle_hash
            and current_evidence
            and current_evidence != stored_evidence_bundle_hash
        ):
            stale_reasons.append("EVIDENCE_BUNDLE_HASH_CHANGED")

        source_status = snapshot.get("source_status") or ""
        if "SUPERSEDED" in str(source_status).upper():
            stale_reasons.append("SOURCE_SUPERSEDED")

        return {
            "stale": len(stale_reasons) > 0,
            "reasons": stale_reasons,
            "current_snapshot": snapshot,
        }
