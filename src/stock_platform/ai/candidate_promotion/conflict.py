"""STEP 11-12 — Existing Candidate / Promotion conflict detection (READ-ONLY)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_promotion.constants import (
    ACTIVE_PROMOTION_STATUSES,
    PROMOTION_RUN_TYPE,
)
from stock_platform.ai.candidate_promotion.entities import (
    AICandidatePromotionLinkEntity,
    AICandidatePromotionRequestEntity,
)
from stock_platform.screener.persistence_models import CandidateResult, CandidateRun


class AICandidatePromotionConflictService:
    """
    기존 Candidate·Promotion 중복 검사.

    Safety: SELECT only — INSERT/UPDATE 금지.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def check(
        self,
        *,
        queue_id: int,
        source_result_hash: str,
        evidence_bundle_hash: str | None,
        exchange_code: str,
        symbol: str,
        promotion_request_id: int | None = None,
        allow_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        warnings: list[str] = []
        details: dict[str, Any] = {}

        active_promotion = self._session.scalar(
            select(AICandidatePromotionRequestEntity)
            .where(
                AICandidatePromotionRequestEntity.queue_id == queue_id,
                AICandidatePromotionRequestEntity.promotion_status.in_(
                    list(ACTIVE_PROMOTION_STATUSES)
                ),
            )
            .limit(1)
        )
        if (
            active_promotion is not None
            and promotion_request_id is not None
            and active_promotion.promotion_request_id != promotion_request_id
        ):
            blockers.append("ACTIVE_PROMOTION_EXISTS")
            details["active_promotion_id"] = active_promotion.promotion_request_id

        completed_same_source = self._session.scalar(
            select(AICandidatePromotionRequestEntity)
            .where(
                AICandidatePromotionRequestEntity.queue_id == queue_id,
                AICandidatePromotionRequestEntity.source_result_hash
                == source_result_hash,
                AICandidatePromotionRequestEntity.promotion_status == "COMPLETED",
            )
            .limit(1)
        )
        if completed_same_source is not None and (
            promotion_request_id is None
            or completed_same_source.promotion_request_id != promotion_request_id
        ):
            blockers.append("PROMOTION_ALREADY_COMPLETED")
            details["completed_promotion_id"] = (
                completed_same_source.promotion_request_id
            )
            details["candidate_run_id"] = completed_same_source.candidate_run_id
            details["candidate_result_id"] = (
                completed_same_source.candidate_result_id
            )

        screener_conflict = self._session.scalar(
            select(CandidateResult)
            .join(CandidateRun, CandidateRun.run_id == CandidateResult.run_id)
            .where(
                CandidateResult.symbol == symbol,
                CandidateResult.exchange_code == exchange_code,
                CandidateRun.run_type == "DAILY",
                CandidateRun.status_code == "COMPLETED",
            )
            .order_by(CandidateResult.created_at.desc())
            .limit(1)
        )
        if screener_conflict is not None:
            warnings.append("ACTIVE_SCREENER_CANDIDATE")
            details["screener_result"] = {
                "result_id": screener_conflict.result_id,
                "run_id": screener_conflict.run_id,
                "rank_no": screener_conflict.rank_no,
            }
            if not allow_override:
                blockers.append("EXISTING_SCREENER_CANDIDATE")
            elif not override_reason or not str(override_reason).strip():
                blockers.append("OVERRIDE_REASON_REQUIRED")

        ai_promotion_result = self._session.scalar(
            select(CandidateResult)
            .join(CandidateRun, CandidateRun.run_id == CandidateResult.run_id)
            .where(
                CandidateResult.symbol == symbol,
                CandidateResult.exchange_code == exchange_code,
                CandidateRun.run_type == PROMOTION_RUN_TYPE,
                CandidateRun.status_code == "COMPLETED",
            )
            .order_by(CandidateResult.created_at.desc())
            .limit(1)
        )
        if ai_promotion_result is not None:
            breakdown = ai_promotion_result.score_breakdown or {}
            prior_hash = breakdown.get("source_result_hash")
            if prior_hash == source_result_hash:
                blockers.append("DUPLICATE_AI_PROMOTION_SOURCE")
                details["prior_result_id"] = ai_promotion_result.result_id

        return {
            "has_conflict": len(blockers) > 0,
            "blockers": blockers,
            "warnings": warnings,
            "details": details,
        }

    def is_consumed(self, *, promotion_request_id: int) -> dict[str, Any]:
        """Rollback 가능 여부 — Link 기준 소비 여부."""
        link = self._session.scalar(
            select(AICandidatePromotionLinkEntity).where(
                AICandidatePromotionLinkEntity.promotion_request_id
                == promotion_request_id
            )
        )
        if link is None:
            return {"consumed": False, "reason": "NO_LINK"}

        if link.rollback_status != "NONE":
            return {"consumed": True, "reason": f"ROLLBACK_{link.rollback_status}"}

        result = self._session.get(CandidateResult, link.candidate_result_id)
        if result is None:
            return {"consumed": False, "reason": "RESULT_MISSING"}

        breakdown = result.score_breakdown or {}
        if breakdown.get("revoked"):
            return {"consumed": True, "reason": "ALREADY_REVOKED"}

        if breakdown.get("strategy_attached") or breakdown.get("order_consumed"):
            return {"consumed": True, "reason": "DOWNSTREAM_CONSUMPTION"}

        return {"consumed": False, "reason": "ELIGIBLE_FOR_ROLLBACK"}
