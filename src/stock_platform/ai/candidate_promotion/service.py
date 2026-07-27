"""STEP 11-12 — Candidate Promotion Gateway Service.

Critical safety:
- Create/Validate/Dry-run/Approve → Candidate INSERT 0
- Only Commit creates CandidateRun+Result (AI_REVIEW_PROMOTION) in ONE transaction
- Dual approval: Requester ≠ First ≠ Final (self-approval blocked)
- Critical findings → never override
- APPROVED_WITH_WARNINGS → warning acknowledgements on final approve
- No trading/order/runtime/scheduler imports
- Do NOT use CandidateRunService.execute_and_save
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_promotion.conflict import (
    AICandidatePromotionConflictService,
)
from stock_platform.ai.candidate_promotion.constants import (
    ACTIVE_PROMOTION_STATUSES,
    DEFAULT_PROMOTION_EXPIRY_HOURS,
    ELIGIBILITY_VERSION,
    MAPPING_VERSION,
    PROMOTABLE_QUEUE_STATUSES,
    PROMOTION_RUN_TYPE,
    PROMOTION_STATUS,
    REFERENCE_DISCLAIMER,
    SCORE_FORMULA_VERSION,
    TERMINAL_PROMOTION_STATUSES,
)
from stock_platform.ai.candidate_promotion.dry_run import (
    AICandidatePromotionDryRunService,
)
from stock_platform.ai.candidate_promotion.eligibility import (
    AICandidatePromotionEligibilityService,
)
from stock_platform.ai.candidate_promotion.entities import (
    AICandidatePromotionApprovalEntity,
    AICandidatePromotionDryRunEntity,
    AICandidatePromotionHistoryEntity,
    AICandidatePromotionLinkEntity,
    AICandidatePromotionRequestEntity,
    AICandidatePromotionValidationEntity,
)
from stock_platform.ai.candidate_promotion.mapping import (
    build_score_inputs,
    candidate_result_hash,
)
from stock_platform.ai.candidate_recommendation_queue.entities import (
    AICandidateRecommendationDecisionEntity,
    AICandidateRecommendationQueueEntity,
    AICandidateRecommendationReviewEntity,
)
from stock_platform.ai.candidate_recommendation_queue.expiration import is_expired
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.screener.persistence_models import CandidateResult, CandidateRun


class AICandidatePromotionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _promotion_key(
    *,
    queue_id: int,
    source_result_hash: str,
    evidence_bundle_hash: str | None,
    mapping_version: str,
    score_formula_version: str,
) -> str:
    raw = (
        f"candidate-promotion:{queue_id}:{source_result_hash}:"
        f"{evidence_bundle_hash or 'none'}:{mapping_version}:{score_formula_version}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:220]


class AICandidatePromotionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._eligibility = AICandidatePromotionEligibilityService(session)
        self._conflict = AICandidatePromotionConflictService(session)
        self._dry_run = AICandidatePromotionDryRunService(session)

    def _get_request(
        self, promotion_request_id: int, *, for_update: bool = False
    ) -> AICandidatePromotionRequestEntity:
        stmt = select(AICandidatePromotionRequestEntity).where(
            AICandidatePromotionRequestEntity.promotion_request_id
            == promotion_request_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        row = self._session.scalar(stmt)
        if row is None:
            raise AICandidatePromotionError(
                "NOT_FOUND", f"promotion {promotion_request_id} missing"
            )
        return row

    def _get_queue(self, queue_id: int) -> AICandidateRecommendationQueueEntity:
        row = self._session.get(AICandidateRecommendationQueueEntity, queue_id)
        if row is None:
            raise AICandidatePromotionError("NOT_FOUND", f"queue {queue_id} missing")
        return row

    def _history(
        self,
        promotion_request_id: int,
        *,
        action: str,
        actor: str,
        previous: str | None = None,
        new: str | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self._session.add(
            AICandidatePromotionHistoryEntity(
                promotion_request_id=promotion_request_id,
                action=action,
                previous_status=previous,
                new_status=new,
                reason=reason,
                requested_by=actor,
                correlation_id=correlation_id,
            )
        )

    def _transition(
        self,
        row: AICandidatePromotionRequestEntity,
        *,
        new_status: str,
        actor: str,
        action: str,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        if new_status not in PROMOTION_STATUS:
            raise AICandidatePromotionError(
                "INVALID_STATUS", f"bad status {new_status}"
            )
        previous = row.promotion_status
        row.promotion_status = new_status
        row.version = (row.version or 0) + 1
        row.updated_at = _now()
        self._history(
            row.promotion_request_id,
            action=action,
            actor=actor,
            previous=previous,
            new=new_status,
            reason=reason,
            correlation_id=correlation_id,
        )

    def _assert_actor_separation(
        self,
        row: AICandidatePromotionRequestEntity,
        actor: str,
        *,
        stage: str,
        first_approver: str | None = None,
    ) -> None:
        if row.requested_by == actor:
            raise AICandidatePromotionError(
                "SELF_APPROVAL_BLOCKED",
                f"requester cannot {stage}",
            )
        if stage == "FINAL" and first_approver and first_approver == actor:
            raise AICandidatePromotionError(
                "SELF_APPROVAL_BLOCKED",
                "first approver cannot final approve",
            )

    def _latest_decision(self, queue_id: int) -> str | None:
        return self._session.scalar(
            select(AICandidateRecommendationDecisionEntity.decision)
            .where(AICandidateRecommendationDecisionEntity.queue_id == queue_id)
            .order_by(
                AICandidateRecommendationDecisionEntity.decision_version.desc()
            )
            .limit(1)
        )

    def _latest_dry_run(
        self, promotion_request_id: int
    ) -> AICandidatePromotionDryRunEntity | None:
        return self._session.scalar(
            select(AICandidatePromotionDryRunEntity)
            .where(
                AICandidatePromotionDryRunEntity.promotion_request_id
                == promotion_request_id
            )
            .order_by(AICandidatePromotionDryRunEntity.dry_run_version.desc())
            .limit(1)
        )

    def _latest_approval(
        self,
        promotion_request_id: int,
        stage: str,
        *,
        status: str | None = None,
    ) -> AICandidatePromotionApprovalEntity | None:
        stmt = (
            select(AICandidatePromotionApprovalEntity)
            .where(
                AICandidatePromotionApprovalEntity.promotion_request_id
                == promotion_request_id,
                AICandidatePromotionApprovalEntity.approval_stage == stage,
            )
            .order_by(AICandidatePromotionApprovalEntity.version.desc())
        )
        if status:
            stmt = stmt.where(
                AICandidatePromotionApprovalEntity.approval_status == status
            )
        return self._session.scalar(stmt.limit(1))

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

    def _write_validations(
        self,
        promotion_request_id: int,
        validation_version: int,
        checks: list[dict[str, Any]],
    ) -> None:
        for check in checks:
            self._session.add(
                AICandidatePromotionValidationEntity(
                    promotion_request_id=promotion_request_id,
                    validation_version=validation_version,
                    validation_type=str(check["validation_type"]),
                    validation_status=str(check["validation_status"]),
                    check_code=str(check["check_code"]),
                    severity=str(check["severity"]),
                    message_sanitized=check.get("message_sanitized"),
                )
            )

    def _public(self, row: AICandidatePromotionRequestEntity) -> dict[str, Any]:
        return {
            "id": row.promotion_request_id,
            "promotion_key": row.promotion_key,
            "queue_id": row.queue_id,
            "source_type": row.source_type,
            "source_id": row.source_id,
            "market_type": row.market_type,
            "exchange_code": row.exchange_code,
            "instrument_id": row.instrument_id,
            "symbol": row.symbol,
            "promotion_status": row.promotion_status,
            "queue_decision_snapshot": row.queue_decision_snapshot,
            "queue_version_snapshot": row.queue_version_snapshot,
            "source_result_hash": row.source_result_hash,
            "evidence_bundle_hash": row.evidence_bundle_hash,
            "eligibility_version": row.eligibility_version,
            "mapping_version": row.mapping_version,
            "score_formula_version": row.score_formula_version,
            "warning_conditions": row.warning_conditions,
            "requested_reason": row.requested_reason,
            "requested_by": row.requested_by,
            "requested_at": (
                row.requested_at.isoformat() if row.requested_at else None
            ),
            "validated_at": (
                row.validated_at.isoformat() if row.validated_at else None
            ),
            "dry_run_at": row.dry_run_at.isoformat() if row.dry_run_at else None,
            "first_approved_at": (
                row.first_approved_at.isoformat()
                if row.first_approved_at
                else None
            ),
            "final_approved_at": (
                row.final_approved_at.isoformat()
                if row.final_approved_at
                else None
            ),
            "committed_at": (
                row.committed_at.isoformat() if row.committed_at else None
            ),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "candidate_run_id": row.candidate_run_id,
            "candidate_result_id": row.candidate_result_id,
            "error_code": row.error_code,
            "version": row.version,
            "correlation_id": row.correlation_id,
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def create(
        self,
        *,
        queue_id: int,
        actor: str,
        reason: str,
        idempotency_key: str,
        allow_existing_candidate_override: bool = False,
        override_reason: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """DRAFT Promotion Request — Candidate INSERT 0."""
        existing = self._session.scalar(
            select(AICandidatePromotionRequestEntity).where(
                AICandidatePromotionRequestEntity.requested_by == actor,
                AICandidatePromotionRequestEntity.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return {
                "idempotent_replay": True,
                "promotion": self._public(existing),
            }

        queue = self._get_queue(queue_id)
        if queue.queue_status not in PROMOTABLE_QUEUE_STATUSES:
            raise AICandidatePromotionError(
                "QUEUE_NOT_PROMOTABLE", queue.queue_status
            )

        eligibility = self._eligibility.validate_queue(queue)
        if not eligibility.get("allowed"):
            raise AICandidatePromotionError(
                "NOT_ELIGIBLE",
                ",".join(eligibility.get("blockers") or []),
            )

        conflict = self._conflict.check(
            queue_id=queue_id,
            source_result_hash=queue.source_result_hash,
            evidence_bundle_hash=queue.evidence_bundle_hash,
            exchange_code=queue.exchange_code,
            symbol=queue.symbol,
            allow_override=allow_existing_candidate_override,
            override_reason=override_reason,
        )
        if conflict.get("has_conflict"):
            raise AICandidatePromotionError(
                "CONFLICT",
                ",".join(conflict.get("blockers") or []),
            )

        source_id = int(
            queue.candidate_assessment_id or queue.candidate_consensus_id or 0
        )
        pkey = _promotion_key(
            queue_id=queue_id,
            source_result_hash=queue.source_result_hash,
            evidence_bundle_hash=queue.evidence_bundle_hash,
            mapping_version=MAPPING_VERSION,
            score_formula_version=SCORE_FORMULA_VERSION,
        )

        dup = self._session.scalar(
            select(AICandidatePromotionRequestEntity).where(
                AICandidatePromotionRequestEntity.promotion_key == pkey,
                AICandidatePromotionRequestEntity.promotion_status.in_(
                    list(ACTIVE_PROMOTION_STATUSES)
                ),
            )
        )
        if dup is not None:
            raise AICandidatePromotionError(
                "DUPLICATE_ACTIVE_PROMOTION",
                f"active promotion {dup.promotion_request_id}",
            )

        latest_decision = self._latest_decision(queue_id)
        warning_conditions: dict[str, Any] | None = None
        if queue.queue_status == "APPROVED_WITH_WARNINGS":
            decision_row = self._session.scalar(
                select(AICandidateRecommendationDecisionEntity)
                .where(
                    AICandidateRecommendationDecisionEntity.queue_id == queue_id
                )
                .order_by(
                    AICandidateRecommendationDecisionEntity.decision_version.desc()
                )
                .limit(1)
            )
            if decision_row and decision_row.warning_conditions:
                warning_conditions = sanitize_for_log(
                    decision_row.warning_conditions
                )

        default_expiry = _now() + timedelta(hours=DEFAULT_PROMOTION_EXPIRY_HOURS)
        expires_at = min(queue.expires_at, default_expiry)

        row = AICandidatePromotionRequestEntity(
            promotion_key=pkey,
            idempotency_key=idempotency_key,
            queue_id=queue_id,
            source_type=queue.source_type,
            source_id=source_id,
            market_type=queue.market_type,
            exchange_code=queue.exchange_code,
            instrument_id=queue.instrument_id,
            symbol=queue.symbol,
            promotion_status="DRAFT",
            queue_decision_snapshot=latest_decision or queue.queue_status,
            queue_version_snapshot=queue.lock_version,
            source_result_hash=queue.source_result_hash,
            evidence_bundle_hash=queue.evidence_bundle_hash,
            eligibility_version=ELIGIBILITY_VERSION,
            mapping_version=MAPPING_VERSION,
            score_formula_version=SCORE_FORMULA_VERSION,
            warning_conditions=warning_conditions,
            requested_reason=reason[:500],
            requested_by=actor,
            expires_at=expires_at,
            correlation_id=correlation_id or str(uuid.uuid4())[:64],
        )
        self._session.add(row)
        self._session.flush()

        self._history(
            row.promotion_request_id,
            action="CREATED",
            actor=actor,
            new="DRAFT",
            reason=reason,
            correlation_id=correlation_id,
        )

        return {
            "idempotent_replay": False,
            "promotion": self._public(row),
            "eligibility": eligibility,
        }

    def validate(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str | None = None,
        allow_existing_candidate_override: bool = False,
        override_reason: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        if row.promotion_status in TERMINAL_PROMOTION_STATUSES:
            raise AICandidatePromotionError("INVALID_STATE", "terminal status")

        queue = self._get_queue(row.queue_id)
        self._transition(
            row,
            new_status="VALIDATING",
            actor=actor,
            action="VALIDATION_STARTED",
            reason=reason,
            correlation_id=correlation_id,
        )

        eligibility = self._eligibility.validate_queue(queue)
        conflict = self._conflict.check(
            queue_id=row.queue_id,
            source_result_hash=row.source_result_hash,
            evidence_bundle_hash=row.evidence_bundle_hash,
            exchange_code=row.exchange_code,
            symbol=row.symbol,
            promotion_request_id=promotion_request_id,
            allow_override=allow_existing_candidate_override,
            override_reason=override_reason,
        )

        checks = list(eligibility.get("checks") or [])
        for code in conflict.get("blockers") or []:
            checks.append(
                {
                    "validation_type": "EXISTING_CANDIDATE",
                    "check_code": code,
                    "validation_status": "FAIL",
                    "severity": "HIGH",
                    "message_sanitized": code,
                }
            )
        for warn in conflict.get("warnings") or []:
            checks.append(
                {
                    "validation_type": "EXISTING_CANDIDATE",
                    "check_code": warn,
                    "validation_status": "WARN",
                    "severity": "MEDIUM",
                    "message_sanitized": warn,
                }
            )
        checks.append(
            {
                "validation_type": "SIDE_EFFECT",
                "check_code": "SIDE_EFFECT_GUARD",
                "validation_status": "PASS",
                "severity": "INFO",
                "message_sanitized": "candidate_insert=0",
            }
        )

        validation_version = int(
            self._session.scalar(
                select(func.max(AICandidatePromotionValidationEntity.validation_version)).where(
                    AICandidatePromotionValidationEntity.promotion_request_id
                    == promotion_request_id
                )
            )
            or 0
        ) + 1
        self._write_validations(promotion_request_id, validation_version, checks)

        allowed = eligibility.get("allowed") and not conflict.get("has_conflict")
        has_warnings = bool(eligibility.get("warnings")) or bool(
            conflict.get("warnings")
        )
        if not allowed:
            self._transition(
                row,
                new_status="BLOCKED",
                actor=actor,
                action="VALIDATION_BLOCKED",
                reason=",".join(
                    (eligibility.get("blockers") or [])
                    + (conflict.get("blockers") or [])
                ),
                correlation_id=correlation_id,
            )
        else:
            new_status = (
                "VALIDATED_WITH_WARNINGS" if has_warnings else "VALIDATED"
            )
            row.validated_at = _now()
            self._transition(
                row,
                new_status=new_status,
                actor=actor,
                action="VALIDATED",
                reason=reason,
                correlation_id=correlation_id,
            )

        return {
            "promotion": self._public(row),
            "validation_version": validation_version,
            "allowed": allowed,
            "checks": checks,
        }

    def dry_run(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str | None = None,
        allow_existing_candidate_override: bool = False,
        override_reason: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Preview only — Candidate INSERT 0."""
        row = self._get_request(promotion_request_id)
        if row.promotion_status not in {
            "VALIDATED",
            "VALIDATED_WITH_WARNINGS",
            "DRY_RUN_COMPLETED",
            "DRY_RUN_READY",
        }:
            raise AICandidatePromotionError(
                "INVALID_STATE",
                f"cannot dry-run from {row.promotion_status}",
            )

        queue = self._get_queue(row.queue_id)
        preview = self._dry_run.build_preview(
            queue=queue,
            promotion_request_id=promotion_request_id,
            allow_existing_candidate_override=allow_existing_candidate_override,
            override_reason=override_reason,
        )
        if not preview.get("allowed"):
            raise AICandidatePromotionError(
                "DRY_RUN_BLOCKED",
                "validation/conflict failed",
            )

        dry_run_version = int(
            self._session.scalar(
                select(func.max(AICandidatePromotionDryRunEntity.dry_run_version)).where(
                    AICandidatePromotionDryRunEntity.promotion_request_id
                    == promotion_request_id
                )
            )
            or 0
        ) + 1

        dry_row = AICandidatePromotionDryRunEntity(
            promotion_request_id=promotion_request_id,
            dry_run_version=dry_run_version,
            candidate_run_preview_jsonb=preview["candidate_run_preview_jsonb"],
            candidate_result_preview_jsonb=preview["candidate_result_preview_jsonb"],
            conflict_summary_jsonb=preview["conflict_summary_jsonb"],
            validation_summary_jsonb=preview["validation_summary_jsonb"],
            side_effect_summary_jsonb=preview["side_effect_summary_jsonb"],
            result_hash=preview["result_hash"],
            created_by=actor,
        )
        self._session.add(dry_row)
        row.dry_run_at = _now()
        self._transition(
            row,
            new_status="DRY_RUN_COMPLETED",
            actor=actor,
            action="DRY_RUN_COMPLETED",
            reason=reason,
            correlation_id=correlation_id,
        )

        return {
            "promotion": self._public(row),
            "dry_run": {
                "id": dry_row.dry_run_id,
                "dry_run_version": dry_run_version,
                "result_hash": preview["result_hash"],
                "candidate_run_preview": preview["candidate_run_preview_jsonb"],
                "candidate_result_preview": preview[
                    "candidate_result_preview_jsonb"
                ],
                "side_effect_summary": preview["side_effect_summary_jsonb"],
                "candidate_insert_count": 0,
            },
        }

    def submit_first_approval(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        if row.promotion_status != "DRY_RUN_COMPLETED":
            raise AICandidatePromotionError("INVALID_STATE", "dry-run required")

        self._session.add(
            AICandidatePromotionApprovalEntity(
                promotion_request_id=promotion_request_id,
                approval_stage="FIRST",
                approval_status="PENDING",
                approved_by=actor,
                approval_reason=reason[:500],
            )
        )
        self._transition(
            row,
            new_status="FIRST_APPROVAL_PENDING",
            actor=actor,
            action="FIRST_APPROVAL_REQUESTED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"promotion": self._public(row)}

    def approve_first(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str,
        manager_override: bool = False,
        override_reason: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        if row.promotion_status != "FIRST_APPROVAL_PENDING":
            raise AICandidatePromotionError("INVALID_STATE", "not pending first")

        self._assert_actor_separation(row, actor, stage="FIRST")

        queue = self._get_queue(row.queue_id)
        eligibility = self._eligibility.validate_queue(queue)
        critical = int(
            (eligibility.get("snapshot") or {}).get("critical_findings_count") or 0
        )
        if critical > 0:
            raise AICandidatePromotionError(
                "CRITICAL_FINDINGS_BLOCK",
                f"{critical} critical findings — override impossible",
            )
        if not eligibility.get("allowed") and not manager_override:
            raise AICandidatePromotionError(
                "NOT_ELIGIBLE",
                ",".join(eligibility.get("blockers") or []),
            )
        if manager_override and not override_reason:
            raise AICandidatePromotionError(
                "OVERRIDE_REASON_REQUIRED", "override needs reason"
            )

        dry = self._latest_dry_run(promotion_request_id)
        if dry is None:
            raise AICandidatePromotionError("DRY_RUN_MISSING", "dry-run required")

        pending = self._latest_approval(promotion_request_id, "FIRST", status="PENDING")
        version = int(
            self._session.scalar(
                select(func.max(AICandidatePromotionApprovalEntity.version)).where(
                    AICandidatePromotionApprovalEntity.promotion_request_id
                    == promotion_request_id,
                    AICandidatePromotionApprovalEntity.approval_stage == "FIRST",
                )
            )
            or 0
        ) + 1

        if pending:
            pending.approval_status = "APPROVED"
            pending.approved_at = _now()
            pending.approved_by = actor
            pending.approval_reason = reason[:500]
            pending.source_result_hash_at_approval = row.source_result_hash
            pending.evidence_bundle_hash_at_approval = row.evidence_bundle_hash
            pending.queue_version_at_approval = queue.lock_version
            pending.dry_run_result_hash = dry.result_hash
            pending.version = version
            approval = pending
        else:
            approval = AICandidatePromotionApprovalEntity(
                promotion_request_id=promotion_request_id,
                approval_stage="FIRST",
                approval_status="APPROVED",
                approved_by=actor,
                approval_reason=reason[:500],
                source_result_hash_at_approval=row.source_result_hash,
                evidence_bundle_hash_at_approval=row.evidence_bundle_hash,
                queue_version_at_approval=queue.lock_version,
                dry_run_result_hash=dry.result_hash,
                approved_at=_now(),
                version=version,
            )
            self._session.add(approval)

        row.first_approved_at = _now()
        self._transition(
            row,
            new_status="FIRST_APPROVED",
            actor=actor,
            action="FIRST_APPROVED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"promotion": self._public(row), "approval_id": approval.approval_id}

    def reject_first(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        self._assert_actor_separation(row, actor, stage="FIRST")
        self._session.add(
            AICandidatePromotionApprovalEntity(
                promotion_request_id=promotion_request_id,
                approval_stage="FIRST",
                approval_status="REJECTED",
                approved_by=actor,
                approval_reason=reason[:500],
                approved_at=_now(),
            )
        )
        self._transition(
            row,
            new_status="REJECTED",
            actor=actor,
            action="FIRST_REJECTED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"promotion": self._public(row)}

    def submit_final_approval(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        if row.promotion_status != "FIRST_APPROVED":
            raise AICandidatePromotionError("INVALID_STATE", "first approval required")

        self._session.add(
            AICandidatePromotionApprovalEntity(
                promotion_request_id=promotion_request_id,
                approval_stage="FINAL",
                approval_status="PENDING",
                approved_by=actor,
                approval_reason=reason[:500],
            )
        )
        self._transition(
            row,
            new_status="FINAL_APPROVAL_PENDING",
            actor=actor,
            action="FINAL_APPROVAL_REQUESTED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"promotion": self._public(row)}

    def approve_final(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str,
        warning_acknowledgements: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        if row.promotion_status != "FINAL_APPROVAL_PENDING":
            raise AICandidatePromotionError("INVALID_STATE", "not pending final")

        first = self._latest_approval(
            promotion_request_id, "FIRST", status="APPROVED"
        )
        first_actor = first.approved_by if first else None
        self._assert_actor_separation(
            row, actor, stage="FINAL", first_approver=first_actor
        )

        queue = self._get_queue(row.queue_id)
        eligibility = self._eligibility.validate_queue(queue)
        critical = int(
            (eligibility.get("snapshot") or {}).get("critical_findings_count") or 0
        )
        if critical > 0:
            raise AICandidatePromotionError(
                "CRITICAL_FINDINGS_BLOCK",
                f"{critical} critical findings",
            )

        if row.queue_decision_snapshot == "APPROVED_WITH_WARNINGS":
            ack = warning_acknowledgements or {}
            if not ack.get("acknowledged"):
                raise AICandidatePromotionError(
                    "WARNING_ACK_REQUIRED",
                    "APPROVED_WITH_WARNINGS requires warning acknowledgements",
                )

        dry = self._latest_dry_run(promotion_request_id)
        if dry is None:
            raise AICandidatePromotionError("DRY_RUN_MISSING", "dry-run required")

        if first and (
            first.source_result_hash_at_approval != row.source_result_hash
            or first.dry_run_result_hash != dry.result_hash
            or first.queue_version_at_approval != queue.lock_version
        ):
            self._transition(
                row,
                new_status="STALE",
                actor=actor,
                action="STALE_ON_FINAL",
                reason="source or dry-run changed",
                correlation_id=correlation_id,
            )
            raise AICandidatePromotionError("STALE", "approval snapshot stale")

        version = int(
            self._session.scalar(
                select(func.max(AICandidatePromotionApprovalEntity.version)).where(
                    AICandidatePromotionApprovalEntity.promotion_request_id
                    == promotion_request_id,
                    AICandidatePromotionApprovalEntity.approval_stage == "FINAL",
                )
            )
            or 0
        ) + 1

        approval = AICandidatePromotionApprovalEntity(
            promotion_request_id=promotion_request_id,
            approval_stage="FINAL",
            approval_status="APPROVED",
            approved_by=actor,
            approval_reason=reason[:500],
            warning_acknowledgements=sanitize_for_log(
                warning_acknowledgements or {}
            ),
            source_result_hash_at_approval=row.source_result_hash,
            evidence_bundle_hash_at_approval=row.evidence_bundle_hash,
            queue_version_at_approval=queue.lock_version,
            dry_run_result_hash=dry.result_hash,
            approved_at=_now(),
            version=version,
        )
        self._session.add(approval)
        row.final_approved_at = _now()
        self._transition(
            row,
            new_status="COMMIT_PENDING",
            actor=actor,
            action="FINAL_APPROVED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"promotion": self._public(row), "approval_id": approval.approval_id}

    def reject_final(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        first = self._latest_approval(
            promotion_request_id, "FIRST", status="APPROVED"
        )
        self._assert_actor_separation(
            row,
            actor,
            stage="FINAL",
            first_approver=first.approved_by if first else None,
        )
        self._session.add(
            AICandidatePromotionApprovalEntity(
                promotion_request_id=promotion_request_id,
                approval_stage="FINAL",
                approval_status="REJECTED",
                approved_by=actor,
                approval_reason=reason[:500],
                approved_at=_now(),
            )
        )
        self._transition(
            row,
            new_status="REJECTED",
            actor=actor,
            action="FINAL_REJECTED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"promotion": self._public(row)}

    def commit(
        self,
        promotion_request_id: int,
        *,
        confirm: bool,
        idempotency_key: str,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        원자적 CandidateRun+Result+Link INSERT — 유일한 Candidate 생성 경로.

        session.flush() only — API layer commits.
        """
        if not confirm:
            raise AICandidatePromotionError(
                "CONFIRM_REQUIRED", "commit requires confirm=true"
            )

        row = self._get_request(promotion_request_id, for_update=True)

        if (
            row.promotion_status == "COMPLETED"
            and row.commit_idempotency_key == idempotency_key
        ):
            return {
                "idempotent_replay": True,
                "promotion": self._public(row),
            }

        if row.promotion_status not in {"COMMIT_PENDING", "FINAL_APPROVED"}:
            raise AICandidatePromotionError(
                "INVALID_STATE", f"cannot commit from {row.promotion_status}"
            )

        if row.requested_by == actor:
            raise AICandidatePromotionError(
                "SELF_APPROVAL_BLOCKED", "requester cannot commit"
            )

        if is_expired(row.expires_at):
            self._transition(
                row,
                new_status="EXPIRED",
                actor=actor,
                action="EXPIRED_ON_COMMIT",
                correlation_id=correlation_id,
            )
            raise AICandidatePromotionError("EXPIRED", "promotion expired")

        first = self._latest_approval(
            promotion_request_id, "FIRST", status="APPROVED"
        )
        final = self._latest_approval(
            promotion_request_id, "FINAL", status="APPROVED"
        )
        if first is None or final is None:
            raise AICandidatePromotionError("APPROVAL_MISSING", "dual approval required")

        if actor in {row.requested_by, first.approved_by, final.approved_by}:
            # Commit operator must differ from requester; may equal final per policy
            if actor == row.requested_by or actor == first.approved_by:
                raise AICandidatePromotionError(
                    "SELF_APPROVAL_BLOCKED", "commit actor separation failed"
                )

        queue = self._get_queue(row.queue_id)
        eligibility = self._eligibility.validate_queue(queue)
        if not eligibility.get("allowed"):
            row.failed_at = _now()
            row.error_code = "COMMIT_PRECONDITION_FAILED"
            row.error_message_sanitized = ",".join(
                eligibility.get("blockers") or []
            )[:2000]
            self._transition(
                row,
                new_status="FAILED",
                actor=actor,
                action="COMMIT_FAILED",
                reason=row.error_message_sanitized,
                correlation_id=correlation_id,
            )
            raise AICandidatePromotionError(
                "COMMIT_BLOCKED",
                row.error_message_sanitized or "precondition failed",
            )

        dry = self._latest_dry_run(promotion_request_id)
        if dry is None or dry.result_hash != final.dry_run_result_hash:
            raise AICandidatePromotionError("STALE", "dry-run hash mismatch")

        conflict = self._conflict.check(
            queue_id=row.queue_id,
            source_result_hash=row.source_result_hash,
            evidence_bundle_hash=row.evidence_bundle_hash,
            exchange_code=row.exchange_code,
            symbol=row.symbol,
            promotion_request_id=promotion_request_id,
        )
        if conflict.get("has_conflict"):
            raise AICandidatePromotionError(
                "CONFLICT",
                ",".join(conflict.get("blockers") or []),
            )

        self._transition(
            row,
            new_status="COMMITTING",
            actor=actor,
            action="COMMIT_STARTED",
            reason=reason,
            correlation_id=correlation_id,
        )

        review_scores = self._review_overall_scores(queue.queue_id)
        critical = int(
            (eligibility.get("snapshot") or {}).get("critical_findings_count") or 0
        )
        warning_count = len(eligibility.get("warnings") or [])
        score_payload = build_score_inputs(
            queue,
            review_overall_scores=review_scores,
            warning_count=warning_count,
            has_critical=critical > 0,
        )

        run_preview = dry.candidate_run_preview_jsonb
        result_preview = dry.candidate_result_preview_jsonb
        trade_date = date.fromisoformat(
            str(result_preview.get("trade_date") or date.today().isoformat())
        )

        # Direct INSERT — CandidateRunService.execute_and_save 사용 금지
        candidate_run = CandidateRun(
            exchange_code=row.exchange_code,
            as_of_date=trade_date,
            run_type=PROMOTION_RUN_TYPE,
            requested_count=1,
            evaluated_count=1,
            skipped_count=0,
            selected_count=1,
            minimum_score=Decimal("0"),
            require_all_rules=False,
            status_code="COMPLETED",
        )
        self._session.add(candidate_run)
        self._session.flush()

        breakdown = dict(result_preview.get("score_breakdown") or {})
        breakdown.update(
            {
                "source_type": "AI_REVIEW_PROMOTION_SCORE",
                "trading_eligibility": False,
                "strategy_eligibility": False,
                "order_eligibility": False,
                "promotion_request_id": promotion_request_id,
                "queue_id": row.queue_id,
                "mapping_version": MAPPING_VERSION,
                "formula_version": SCORE_FORMULA_VERSION,
            }
        )

        candidate_result = CandidateResult(
            run_id=candidate_run.run_id,
            rank_no=1,
            exchange_code=row.exchange_code,
            symbol=row.symbol,
            trade_date=trade_date,
            total_score=Decimal(str(score_payload["total_score"])),
            rules_passed_count=0,
            all_rules_passed=False,
            rule_result=result_preview.get("rule_result") or {},
            score_breakdown=breakdown,
        )
        self._session.add(candidate_result)
        self._session.flush()

        result_hash = candidate_result_hash(result_preview)
        link = AICandidatePromotionLinkEntity(
            promotion_request_id=promotion_request_id,
            queue_id=row.queue_id,
            candidate_run_id=candidate_run.run_id,
            candidate_result_id=candidate_result.result_id,
            candidate_result_hash=result_hash,
            promoted_by=actor,
            rollback_status="NONE",
        )
        self._session.add(link)

        row.candidate_run_id = candidate_run.run_id
        row.candidate_result_id = candidate_result.result_id
        row.commit_idempotency_key = idempotency_key
        row.committed_at = _now()
        self._transition(
            row,
            new_status="COMPLETED",
            actor=actor,
            action="COMPLETED",
            reason=reason,
            correlation_id=idempotency_key,
        )

        self._session.flush()

        # STEP 11-13: commit 직후 lifecycle + provenance 보장 (flush only, 동일 session)
        from stock_platform.ai.candidate_lifecycle.service import (
            AICandidateLifecycleError,
            AICandidateLifecycleService,
        )

        try:
            AICandidateLifecycleService(self._session).ensure_lifecycle(
                candidate_result.result_id,
                actor=actor,
            )
        except AICandidateLifecycleError:
            # lifecycle는 API/backfill로 보장 가능 — commit 자체는 유지
            pass

        return {
            "idempotent_replay": False,
            "promotion": self._public(row),
            "candidate_run_id": candidate_run.run_id,
            "candidate_result_id": candidate_result.result_id,
            "total_score": str(score_payload["total_score"]),
        }

    def cancel(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        if row.promotion_status in {"COMPLETED", "CANCELLED", "ROLLED_BACK"}:
            raise AICandidatePromotionError("INVALID_STATE", "cannot cancel")
        row.cancelled_at = _now()
        self._transition(
            row,
            new_status="CANCELLED",
            actor=actor,
            action="CANCELLED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"promotion": self._public(row)}

    def expire(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str = "expired",
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        if row.promotion_status in TERMINAL_PROMOTION_STATUSES:
            raise AICandidatePromotionError("INVALID_STATE", "terminal")
        if not is_expired(row.expires_at):
            raise AICandidatePromotionError("NOT_EXPIRED", "still active")
        self._transition(
            row,
            new_status="EXPIRED",
            actor=actor,
            action="EXPIRED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"promotion": self._public(row)}

    def revalidate(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.validate(
            promotion_request_id,
            actor=actor,
            reason=reason,
            **kwargs,
        )

    def recreate_dry_run(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        if row.promotion_status in {"COMPLETED", "COMMITTING"}:
            raise AICandidatePromotionError("INVALID_STATE", "cannot recreate dry-run")
        return self.dry_run(
            promotion_request_id,
            actor=actor,
            reason=reason,
            **kwargs,
        )

    def rollback(
        self,
        promotion_request_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        if row.promotion_status != "COMPLETED":
            raise AICandidatePromotionError("INVALID_STATE", "only completed rollback")

        consumption = self._conflict.is_consumed(
            promotion_request_id=promotion_request_id
        )
        if consumption.get("consumed"):
            self._transition(
                row,
                new_status="ROLLBACK_REQUIRED",
                actor=actor,
                action="ROLLBACK_BLOCKED",
                reason=str(consumption.get("reason")),
                correlation_id=correlation_id,
            )
            raise AICandidatePromotionError(
                "BLOCKED_ROLLBACK",
                str(consumption.get("reason")),
            )

        link = self._session.scalar(
            select(AICandidatePromotionLinkEntity).where(
                AICandidatePromotionLinkEntity.promotion_request_id
                == promotion_request_id
            )
        )
        if link is None:
            raise AICandidatePromotionError("NO_LINK", "missing promotion link")

        run = self._session.get(CandidateRun, link.candidate_run_id)
        result = self._session.get(CandidateResult, link.candidate_result_id)
        if run:
            run.status_code = "ROLLED_BACK"
        if result:
            breakdown = dict(result.score_breakdown or {})
            breakdown["revoked"] = True
            breakdown["trading_eligibility"] = False
            breakdown["strategy_eligibility"] = False
            breakdown["order_eligibility"] = False
            result.score_breakdown = breakdown

        link.rollback_status = "ROLLED_BACK"
        link.rolled_back_at = _now()
        link.rollback_reason = reason[:500]

        self._transition(
            row,
            new_status="ROLLED_BACK",
            actor=actor,
            action="ROLLED_BACK",
            reason=reason,
            correlation_id=correlation_id,
        )
        self._session.flush()
        return {"promotion": self._public(row)}

    def list(
        self,
        *,
        status: str | None = None,
        exchange_code: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        stmt = select(AICandidatePromotionRequestEntity).order_by(
            AICandidatePromotionRequestEntity.promotion_request_id.desc()
        )
        if status:
            stmt = stmt.where(
                AICandidatePromotionRequestEntity.promotion_status == status
            )
        if exchange_code:
            stmt = stmt.where(
                AICandidatePromotionRequestEntity.exchange_code == exchange_code
            )
        if symbol:
            stmt = stmt.where(AICandidatePromotionRequestEntity.symbol == symbol)
        rows = list(self._session.scalars(stmt.limit(limit).offset(offset)))
        return {
            "items": [self._public(r) for r in rows],
            "limit": limit,
            "offset": offset,
        }

    def get(self, promotion_request_id: int) -> dict[str, Any]:
        return {"promotion": self._public(self._get_request(promotion_request_id))}

    def get_validations(self, promotion_request_id: int) -> dict[str, Any]:
        self._get_request(promotion_request_id)
        rows = list(
            self._session.scalars(
                select(AICandidatePromotionValidationEntity)
                .where(
                    AICandidatePromotionValidationEntity.promotion_request_id
                    == promotion_request_id
                )
                .order_by(
                    AICandidatePromotionValidationEntity.validation_version,
                    AICandidatePromotionValidationEntity.validation_id,
                )
            )
        )
        return {
            "items": [
                {
                    "id": r.validation_id,
                    "validation_version": r.validation_version,
                    "validation_type": r.validation_type,
                    "validation_status": r.validation_status,
                    "check_code": r.check_code,
                    "severity": r.severity,
                    "message": r.message_sanitized,
                    "created_at": (
                        r.created_at.isoformat() if r.created_at else None
                    ),
                }
                for r in rows
            ]
        }

    def get_dry_runs(self, promotion_request_id: int) -> dict[str, Any]:
        self._get_request(promotion_request_id)
        rows = list(
            self._session.scalars(
                select(AICandidatePromotionDryRunEntity)
                .where(
                    AICandidatePromotionDryRunEntity.promotion_request_id
                    == promotion_request_id
                )
                .order_by(AICandidatePromotionDryRunEntity.dry_run_version)
            )
        )
        return {
            "items": [
                {
                    "id": r.dry_run_id,
                    "dry_run_version": r.dry_run_version,
                    "result_hash": r.result_hash,
                    "created_by": r.created_by,
                    "created_at": (
                        r.created_at.isoformat() if r.created_at else None
                    ),
                    "candidate_insert_count": 0,
                }
                for r in rows
            ]
        }

    def get_approvals(self, promotion_request_id: int) -> dict[str, Any]:
        self._get_request(promotion_request_id)
        rows = list(
            self._session.scalars(
                select(AICandidatePromotionApprovalEntity)
                .where(
                    AICandidatePromotionApprovalEntity.promotion_request_id
                    == promotion_request_id
                )
                .order_by(
                    AICandidatePromotionApprovalEntity.approval_stage,
                    AICandidatePromotionApprovalEntity.version,
                )
            )
        )
        return {
            "items": [
                {
                    "id": r.approval_id,
                    "approval_stage": r.approval_stage,
                    "approval_status": r.approval_status,
                    "approved_by": r.approved_by,
                    "approval_reason": r.approval_reason,
                    "warning_acknowledgements": r.warning_acknowledgements,
                    "dry_run_result_hash": r.dry_run_result_hash,
                    "approved_at": (
                        r.approved_at.isoformat() if r.approved_at else None
                    ),
                }
                for r in rows
            ]
        }

    def get_history(self, promotion_request_id: int) -> dict[str, Any]:
        self._get_request(promotion_request_id)
        rows = list(
            self._session.scalars(
                select(AICandidatePromotionHistoryEntity)
                .where(
                    AICandidatePromotionHistoryEntity.promotion_request_id
                    == promotion_request_id
                )
                .order_by(AICandidatePromotionHistoryEntity.created_at)
            )
        )
        return {
            "items": [
                {
                    "id": r.history_id,
                    "action": r.action,
                    "previous_status": r.previous_status,
                    "new_status": r.new_status,
                    "reason": r.reason,
                    "requested_by": r.requested_by,
                    "correlation_id": r.correlation_id,
                    "created_at": (
                        r.created_at.isoformat() if r.created_at else None
                    ),
                }
                for r in rows
            ]
        }

    def get_candidate(self, promotion_request_id: int) -> dict[str, Any]:
        row = self._get_request(promotion_request_id)
        if not row.candidate_result_id:
            return {"candidate": None}
        result = self._session.get(CandidateResult, row.candidate_result_id)
        run = (
            self._session.get(CandidateRun, row.candidate_run_id)
            if row.candidate_run_id
            else None
        )
        if result is None:
            return {"candidate": None}
        return {
            "candidate": {
                "result_id": result.result_id,
                "run_id": result.run_id,
                "run_type": run.run_type if run else None,
                "symbol": result.symbol,
                "exchange_code": result.exchange_code,
                "total_score": str(result.total_score),
                "score_breakdown": result.score_breakdown,
                "rule_result": result.rule_result,
            }
        }

    def compare(
        self, promotion_request_id: int, other_promotion_request_id: int
    ) -> dict[str, Any]:
        a = self._get_request(promotion_request_id)
        b = self._get_request(other_promotion_request_id)
        return {
            "promotion_a": self._public(a),
            "promotion_b": self._public(b),
            "same_queue": a.queue_id == b.queue_id,
            "same_symbol": a.symbol == b.symbol and a.exchange_code == b.exchange_code,
            "same_source_hash": a.source_result_hash == b.source_result_hash,
        }

    def dashboard_summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for status in PROMOTION_STATUS:
            count = self._session.scalar(
                select(func.count())
                .select_from(AICandidatePromotionRequestEntity)
                .where(
                    AICandidatePromotionRequestEntity.promotion_status == status
                )
            )
            counts[status] = int(count or 0)

        completed_today = self._session.scalar(
            select(func.count())
            .select_from(AICandidatePromotionRequestEntity)
            .where(
                AICandidatePromotionRequestEntity.promotion_status == "COMPLETED",
                func.date(AICandidatePromotionRequestEntity.committed_at)
                == date.today(),
            )
        )

        return {
            "status_counts": counts,
            "completed_today": int(completed_today or 0),
            "candidate_created_count": counts.get("COMPLETED", 0),
            "disclaimer": REFERENCE_DISCLAIMER,
        }
