"""STEP 11-12 — Promotion Dry-run (Candidate INSERT 0)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_promotion.conflict import (
    AICandidatePromotionConflictService,
)
from stock_platform.ai.candidate_promotion.constants import DRY_RUN_VERSION
from stock_platform.ai.candidate_promotion.eligibility import (
    AICandidatePromotionEligibilityService,
)
from stock_platform.ai.candidate_promotion.mapping import (
    build_candidate_result_preview,
    build_candidate_run_preview,
    build_score_inputs,
)
from stock_platform.ai.candidate_recommendation_queue.entities import (
    AICandidateRecommendationQueueEntity,
    AICandidateRecommendationReviewEntity,
)
from stock_platform.ai.providers.security import sanitize_for_log


class AICandidatePromotionDryRunService:
    """
    Dry-run 미리보기 — DB Candidate INSERT 0.

    Safety: preview JSON만 반환/저장.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._eligibility = AICandidatePromotionEligibilityService(session)
        self._conflict = AICandidatePromotionConflictService(session)

    def build_preview(
        self,
        *,
        queue: AICandidateRecommendationQueueEntity,
        promotion_request_id: int,
        allow_existing_candidate_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        eligibility = self._eligibility.validate_queue(queue)
        conflict = self._conflict.check(
            queue_id=queue.queue_id,
            source_result_hash=queue.source_result_hash,
            evidence_bundle_hash=queue.evidence_bundle_hash,
            exchange_code=queue.exchange_code,
            symbol=queue.symbol,
            promotion_request_id=promotion_request_id,
            allow_override=allow_existing_candidate_override,
            override_reason=override_reason,
        )

        review_scores = self._review_overall_scores(queue.queue_id)
        critical = int(
            (eligibility.get("snapshot") or {}).get("critical_findings_count") or 0
        )
        warning_count = len(eligibility.get("warnings") or []) + len(
            conflict.get("warnings") or []
        )
        score_payload = build_score_inputs(
            queue,
            review_overall_scores=review_scores,
            warning_count=warning_count,
            has_critical=critical > 0,
        )

        run_preview = build_candidate_run_preview(
            queue=queue,
            promotion_request_id=promotion_request_id,
        )
        result_preview = build_candidate_result_preview(
            queue=queue,
            promotion_request_id=promotion_request_id,
            score_payload=score_payload,
        )

        side_effect = self._eligibility.side_effect_guard_summary()
        validation_summary = sanitize_for_log(
            {
                "allowed": eligibility.get("allowed") and not conflict.get(
                    "has_conflict"
                ),
                "eligibility_blockers": eligibility.get("blockers"),
                "conflict_blockers": conflict.get("blockers"),
                "warnings": (eligibility.get("warnings") or [])
                + (conflict.get("warnings") or []),
            }
        )

        payload = sanitize_for_log(
            {
                "dry_run_version": DRY_RUN_VERSION,
                "promotion_request_id": promotion_request_id,
                "queue_id": queue.queue_id,
                "candidate_run_preview": run_preview,
                "candidate_result_preview": result_preview,
                "score": score_payload,
                "validation_summary": validation_summary,
                "conflict_summary": conflict,
                "side_effect_summary": side_effect,
                "db_rows_to_insert_on_commit": {
                    "candidate_run": 1,
                    "candidate_result": 1,
                    "promotion_link": 1,
                },
                "db_rows_inserted_in_dry_run": 0,
            }
        )
        result_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:64]

        return {
            "candidate_run_preview_jsonb": run_preview,
            "candidate_result_preview_jsonb": result_preview,
            "conflict_summary_jsonb": conflict,
            "validation_summary_jsonb": validation_summary,
            "side_effect_summary_jsonb": side_effect,
            "score": score_payload,
            "result_hash": result_hash,
            "allowed": bool(validation_summary.get("allowed")),
        }

    def _review_overall_scores(self, queue_id: int) -> list[float]:
        rows = list(
            self._session.scalars(
                select(AICandidateRecommendationReviewEntity).where(
                    AICandidateRecommendationReviewEntity.queue_id == queue_id,
                    AICandidateRecommendationReviewEntity.review_status
                    == "SUBMITTED",
                )
            )
        )
        return [
            float(r.overall_score)
            for r in rows
            if r.overall_score is not None
        ]
