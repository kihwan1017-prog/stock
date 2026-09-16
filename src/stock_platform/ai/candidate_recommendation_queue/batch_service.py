"""STEP 11-11 — Recommendation Queue Batch (명시적 source 목록만)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.candidate_recommendation_queue.constants import (
    MAX_BATCH_CREATE,
    REFERENCE_DISCLAIMER,
)
from stock_platform.ai.candidate_recommendation_queue.service import (
    AIRecommendationQueueError,
    AIRecommendationQueueService,
)


class AIRecommendationQueueBatchService:
    """
    Safety: batch create/queue only — no strategy.candidate INSERT,
    no AI Execution, no external AI, no trading/order/runtime imports.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._svc = AIRecommendationQueueService(session)

    def create_batch(
        self,
        *,
        actor: str,
        reason: str,
        sources: list[dict[str, Any]],
        priority: str = "NORMAL",
        auto_queue: bool = False,
        allow_existing_candidate_override: bool = False,
        override_reason: str | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not sources:
            raise AIRecommendationQueueError(
                "EMPTY_SOURCES", "explicit source list required"
            )
        if len(sources) > MAX_BATCH_CREATE:
            raise AIRecommendationQueueError(
                "BATCH_LIMIT", f"max {MAX_BATCH_CREATE} sources"
            )

        created: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for idx, src in enumerate(sources):
            source_type = str(src.get("source_type") or "")
            assessment_id = src.get("candidate_assessment_id")
            consensus_id = src.get("candidate_consensus_id")
            try:
                result = self._svc.create(
                    actor=actor,
                    reason=reason,
                    source_type=source_type,
                    candidate_assessment_id=assessment_id,
                    candidate_consensus_id=consensus_id,
                    priority=str(src.get("priority") or priority),
                    allow_existing_candidate_override=(
                        allow_existing_candidate_override
                        or bool(src.get("allow_existing_candidate_override"))
                    ),
                    override_reason=override_reason or src.get("override_reason"),
                    expiry_hours=src.get("expiry_hours"),
                    idempotency_key=f"{idempotency_key}:{idx}"[:64],
                )
                queue = result["queue"]
                if auto_queue and not result.get("idempotent_replay"):
                    queued = self._svc.queue(
                        queue["id"],
                        actor=actor,
                        reason=f"batch queue {idx}",
                    )
                    queue = queued["queue"]
                created.append({"index": idx, "queue": queue})
            except AIRecommendationQueueError as exc:
                errors.append(
                    {
                        "index": idx,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )

        return {
            "created": created,
            "errors": errors,
            "created_count": len(created),
            "error_count": len(errors),
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def expire_batch(
        self,
        *,
        actor: str,
        queue_ids: list[int],
        reason: str = "batch expire",
    ) -> dict[str, Any]:
        expired: list[int] = []
        errors: list[dict[str, Any]] = []
        for qid in queue_ids:
            try:
                self._svc.expire(qid, actor=actor, reason=reason)
                expired.append(qid)
            except AIRecommendationQueueError as exc:
                errors.append({"queue_id": qid, "code": exc.code, "message": exc.message})
        return {"expired": expired, "errors": errors}
