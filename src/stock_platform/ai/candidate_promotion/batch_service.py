"""STEP 11-12 — Promotion Batch (명시적 queue_id 목록, 개별 create)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.candidate_promotion.constants import (
    MAX_BATCH,
    REFERENCE_DISCLAIMER,
)
from stock_platform.ai.candidate_promotion.service import (
    AICandidatePromotionError,
    AICandidatePromotionService,
)


class AICandidatePromotionBatchService:
    """
    Safety: batch create only — 각 Item 개별 Promotion Request.
    단일 Approval/Commit으로 전체 처리 금지.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._svc = AICandidatePromotionService(session)

    def create_batch(
        self,
        *,
        actor: str,
        reason: str,
        queue_ids: list[int],
        idempotency_key: str,
        allow_existing_candidate_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        if not queue_ids:
            raise AICandidatePromotionError(
                "EMPTY_QUEUE_IDS", "explicit queue_id list required"
            )
        if len(queue_ids) > MAX_BATCH:
            raise AICandidatePromotionError(
                "BATCH_LIMIT", f"max {MAX_BATCH} queue ids"
            )

        created: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for idx, queue_id in enumerate(queue_ids):
            try:
                result = self._svc.create(
                    queue_id=queue_id,
                    actor=actor,
                    reason=reason,
                    allow_existing_candidate_override=(
                        allow_existing_candidate_override
                    ),
                    override_reason=override_reason,
                    idempotency_key=f"{idempotency_key}:{idx}"[:64],
                )
                created.append(
                    {
                        "index": idx,
                        "queue_id": queue_id,
                        "promotion": result["promotion"],
                        "idempotent_replay": result.get("idempotent_replay", False),
                    }
                )
            except AICandidatePromotionError as exc:
                errors.append(
                    {
                        "index": idx,
                        "queue_id": queue_id,
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
            "note": "Each item requires individual validate/dry-run/approval/commit",
        }
