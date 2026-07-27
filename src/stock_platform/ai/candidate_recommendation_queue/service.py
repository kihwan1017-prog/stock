"""STEP 11-11 — Candidate Recommendation Queue Service.

Safety (enforced in logic + comments):
- create → DRAFT only; queue() / decide() are separate transitions
- No strategy.candidate INSERT
- No trading/order/runtime/scheduler imports
- No AI Execution task additions / no external AI
- APPROVED_FOR_CONSIDERATION ≠ candidate registration
- Self-approval blocked unless manager_override
- Critical findings → never approve even with override
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_recommendation_queue.constants import (
    ASSIGNMENT_STATUS,
    CONSIDERATION_LABEL,
    DECISION,
    ELIGIBILITY_VERSION,
    FINDING_TYPES,
    PRIORITY,
    QUEUE_ENGINE_VERSION,
    QUEUE_STATUS,
    RECOMMENDATION_SCOPES,
    REFERENCE_DISCLAIMER,
    REVIEW_FORMULA_VERSION,
    REVIEW_STATUS,
    SEVERITIES,
    SOURCE_TYPES,
    TERMINAL_QUEUE_STATUSES,
)
from stock_platform.ai.candidate_recommendation_queue.eligibility import (
    AIRecommendationQueueEligibilityService,
)
from stock_platform.ai.candidate_recommendation_queue.entities import (
    AICandidateRecommendationAssignmentEntity,
    AICandidateRecommendationDecisionEntity,
    AICandidateRecommendationFindingEntity,
    AICandidateRecommendationHistoryEntity,
    AICandidateRecommendationQueueEntity,
    AICandidateRecommendationReviewEntity,
)
from stock_platform.ai.candidate_recommendation_queue.expiration import (
    compute_expires_at,
    is_expired,
)
from stock_platform.ai.candidate_recommendation_queue.promotion_eligibility import (
    build_promotion_eligibility_snapshot,
)
from stock_platform.ai.candidate_recommendation_queue.rubric import (
    compute_overall_score,
    validate_optional_score,
)
from stock_platform.ai.candidate_recommendation_queue.staleness import (
    AIRecommendationQueueStalenessService,
)
from stock_platform.ai.providers.security import sanitize_for_log


class AIRecommendationQueueError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _queue_key(
    *,
    source_type: str,
    source_id: int,
    source_result_hash: str,
    symbol: str,
    exchange_code: str,
) -> str:
    raw = (
        f"rec-queue:{source_type}:{source_id}:{source_result_hash}:"
        f"{exchange_code}:{symbol}:{QUEUE_ENGINE_VERSION}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:220]


class AIRecommendationQueueService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._eligibility = AIRecommendationQueueEligibilityService(session)
        self._staleness = AIRecommendationQueueStalenessService(session)

    def _get_queue(self, queue_id: int) -> AICandidateRecommendationQueueEntity:
        row = self._session.get(AICandidateRecommendationQueueEntity, queue_id)
        if row is None:
            raise AIRecommendationQueueError("NOT_FOUND", f"queue {queue_id} missing")
        return row

    def _history(
        self,
        queue_id: int,
        *,
        action: str,
        actor: str,
        previous: str | None = None,
        new: str | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self._session.add(
            AICandidateRecommendationHistoryEntity(
                queue_id=queue_id,
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
        row: AICandidateRecommendationQueueEntity,
        *,
        new_status: str,
        actor: str,
        action: str,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        if new_status not in QUEUE_STATUS:
            raise AIRecommendationQueueError(
                "INVALID_STATUS", f"bad status {new_status}"
            )
        previous = row.queue_status
        row.queue_status = new_status
        row.lock_version = (row.lock_version or 0) + 1
        row.updated_at = _now()
        self._history(
            row.queue_id,
            action=action,
            actor=actor,
            previous=previous,
            new=new_status,
            reason=reason,
            correlation_id=correlation_id,
        )

    def _public(self, row: AICandidateRecommendationQueueEntity) -> dict[str, Any]:
        return {
            "id": row.queue_id,
            "queue_key": row.queue_key,
            "source_type": row.source_type,
            "candidate_assessment_id": row.candidate_assessment_id,
            "candidate_consensus_id": row.candidate_consensus_id,
            "market_type": row.market_type,
            "exchange_code": row.exchange_code,
            "symbol": row.symbol,
            "instrument_id": row.instrument_id,
            "queue_status": row.queue_status,
            "priority": row.priority,
            "source_result_hash": row.source_result_hash,
            "evidence_bundle_hash": row.evidence_bundle_hash,
            "source_review_decision": row.source_review_decision,
            "source_quality_score": row.source_quality_score,
            "analytical_score": row.analytical_score,
            "risk_score": row.risk_score,
            "confidence": row.confidence,
            "agreement_level": row.agreement_level,
            "disagreement_level": row.disagreement_level,
            "provider_diversity": row.provider_diversity,
            "eligibility_version": row.eligibility_version,
            "eligibility_snapshot": row.eligibility_snapshot,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "assigned_to": row.assigned_to,
            "assigned_at": (
                row.assigned_at.isoformat() if row.assigned_at else None
            ),
            "review_started_at": (
                row.review_started_at.isoformat()
                if row.review_started_at
                else None
            ),
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            "superseded_at": (
                row.superseded_at.isoformat() if row.superseded_at else None
            ),
            "superseded_by_id": row.superseded_by_id,
            "lock_version": row.lock_version,
            "created_by": row.created_by,
            "reason": row.reason,
            "correlation_id": row.correlation_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "disclaimer": REFERENCE_DISCLAIMER,
            "consideration_label": CONSIDERATION_LABEL,
        }

    def _public_review(
        self, row: AICandidateRecommendationReviewEntity
    ) -> dict[str, Any]:
        return {
            "id": row.review_id,
            "queue_id": row.queue_id,
            "review_version": row.review_version,
            "review_status": row.review_status,
            "reviewer_id": row.reviewer_id,
            "summary": row.summary,
            "eligibility_score": row.eligibility_score,
            "analytical_quality_score": row.analytical_quality_score,
            "evidence_quality_score": row.evidence_quality_score,
            "risk_awareness_score": row.risk_awareness_score,
            "consistency_score": row.consistency_score,
            "safety_score": row.safety_score,
            "overall_score": row.overall_score,
            "recommendation_scope": row.recommendation_scope,
            "submitted_at": (
                row.submitted_at.isoformat() if row.submitted_at else None
            ),
            "amended_from_id": row.amended_from_id,
            "amendment_reason": row.amendment_reason,
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def _public_finding(
        self, row: AICandidateRecommendationFindingEntity
    ) -> dict[str, Any]:
        return {
            "id": row.finding_id,
            "review_id": row.review_id,
            "finding_type": row.finding_type,
            "severity": row.severity,
            "field_path": row.field_path,
            "description_sanitized": row.description_sanitized,
            "requires_resolution": row.requires_resolution,
            "resolution_status": row.resolution_status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _public_decision(
        self, row: AICandidateRecommendationDecisionEntity
    ) -> dict[str, Any]:
        return {
            "id": row.decision_id,
            "queue_id": row.queue_id,
            "decision_version": row.decision_version,
            "decision": row.decision,
            "decision_reason": row.decision_reason,
            "warning_conditions": row.warning_conditions,
            "decided_by": row.decided_by,
            "manager_override": row.manager_override,
            "override_reason": row.override_reason,
            "critical_findings_count": row.critical_findings_count,
            "unresolved_high_findings_count": row.unresolved_high_findings_count,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "disclaimer": REFERENCE_DISCLAIMER,
            "consideration_label": CONSIDERATION_LABEL,
        }

    def _active_assignment(
        self, queue_id: int
    ) -> AICandidateRecommendationAssignmentEntity | None:
        return self._session.scalar(
            select(AICandidateRecommendationAssignmentEntity)
            .where(
                AICandidateRecommendationAssignmentEntity.queue_id == queue_id,
                AICandidateRecommendationAssignmentEntity.assignment_status.in_(
                    ("ACTIVE", "ACCEPTED")
                ),
            )
            .order_by(
                AICandidateRecommendationAssignmentEntity.assigned_at.desc()
            )
            .limit(1)
        )

    def _latest_submitted_reviews(
        self, queue_id: int
    ) -> list[AICandidateRecommendationReviewEntity]:
        return list(
            self._session.scalars(
                select(AICandidateRecommendationReviewEntity).where(
                    AICandidateRecommendationReviewEntity.queue_id == queue_id,
                    AICandidateRecommendationReviewEntity.review_status.in_(
                        ("SUBMITTED", "AMENDED")
                    ),
                )
            ).all()
        )

    def _finding_counts(
        self, queue_id: int
    ) -> tuple[int, int]:
        reviews = self._latest_submitted_reviews(queue_id)
        review_ids = [r.review_id for r in reviews]
        if not review_ids:
            return 0, 0
        findings = list(
            self._session.scalars(
                select(AICandidateRecommendationFindingEntity).where(
                    AICandidateRecommendationFindingEntity.review_id.in_(
                        review_ids
                    )
                )
            ).all()
        )
        critical = sum(1 for f in findings if f.severity == "CRITICAL")
        unresolved_high = sum(
            1
            for f in findings
            if f.severity == "HIGH"
            and f.resolution_status == "OPEN"
            and f.requires_resolution
        )
        return critical, unresolved_high

    def validate(
        self,
        *,
        source_type: str,
        candidate_assessment_id: int | None = None,
        candidate_consensus_id: int | None = None,
        allow_existing_candidate_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return self._eligibility.validate_source(
            source_type=source_type,
            candidate_assessment_id=candidate_assessment_id,
            candidate_consensus_id=candidate_consensus_id,
            allow_existing_candidate_override=allow_existing_candidate_override,
            override_reason=override_reason,
        )

    def create(
        self,
        *,
        actor: str,
        reason: str,
        source_type: str,
        candidate_assessment_id: int | None = None,
        candidate_consensus_id: int | None = None,
        priority: str = "NORMAL",
        allow_existing_candidate_override: bool = False,
        override_reason: str | None = None,
        expiry_hours: float | None = None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        DRAFT 큐 항목만 생성 — queue()/decide() 와 분리.
        strategy.candidate INSERT / trading side-effect 없음.
        """
        if source_type not in SOURCE_TYPES:
            raise AIRecommendationQueueError("INVALID_SOURCE_TYPE", source_type)
        if priority not in PRIORITY:
            raise AIRecommendationQueueError("INVALID_PRIORITY", priority)

        existing = self._session.scalar(
            select(AICandidateRecommendationQueueEntity).where(
                AICandidateRecommendationQueueEntity.created_by == actor,
                AICandidateRecommendationQueueEntity.idempotency_key
                == idempotency_key,
            )
        )
        if existing is not None:
            return {
                "idempotent_replay": True,
                "queue": self._public(existing),
            }

        eligibility = self.validate(
            source_type=source_type,
            candidate_assessment_id=candidate_assessment_id,
            candidate_consensus_id=candidate_consensus_id,
            allow_existing_candidate_override=allow_existing_candidate_override,
            override_reason=override_reason,
        )
        if not eligibility.get("allowed"):
            raise AIRecommendationQueueError(
                "NOT_ELIGIBLE",
                ",".join(eligibility.get("reasons") or []),
            )

        snap = eligibility["snapshot"]
        source_id = int(
            snap.get("candidate_assessment_id")
            or snap.get("candidate_consensus_id")
            or 0
        )
        source_hash = str(snap.get("source_result_hash") or "")
        market_type = str(snap.get("market_type") or "STOCK")
        symbol = str(snap.get("symbol") or "")
        exchange_code = str(snap.get("exchange_code") or "")

        qkey = _queue_key(
            source_type=source_type,
            source_id=source_id,
            source_result_hash=source_hash,
            symbol=symbol,
            exchange_code=exchange_code,
        )

        dup = self._session.scalar(
            select(AICandidateRecommendationQueueEntity).where(
                AICandidateRecommendationQueueEntity.queue_key == qkey,
                AICandidateRecommendationQueueEntity.queue_status.notin_(
                    list(TERMINAL_QUEUE_STATUSES)
                ),
            )
        )
        if dup is not None:
            raise AIRecommendationQueueError(
                "DUPLICATE_ACTIVE_QUEUE",
                f"active queue {dup.queue_id} exists",
            )

        expires_at = compute_expires_at(
            market_type=market_type,
            requested_hours=expiry_hours,
        )

        row = AICandidateRecommendationQueueEntity(
            queue_key=qkey,
            idempotency_key=idempotency_key,
            source_type=source_type,
            candidate_assessment_id=snap.get("candidate_assessment_id"),
            candidate_consensus_id=snap.get("candidate_consensus_id"),
            market_type=market_type,
            exchange_code=exchange_code,
            instrument_id=snap.get("instrument_id"),
            symbol=symbol,
            queue_status="DRAFT",
            priority=priority,
            source_result_hash=source_hash,
            evidence_bundle_hash=snap.get("evidence_bundle_hash"),
            source_review_decision=snap.get("source_review_decision"),
            source_quality_score=snap.get("source_quality_score"),
            analytical_score=snap.get("analytical_score"),
            risk_score=snap.get("risk_score"),
            confidence=snap.get("confidence"),
            agreement_level=snap.get("agreement_level"),
            disagreement_level=snap.get("disagreement_level"),
            provider_diversity=snap.get("provider_diversity"),
            eligibility_version=ELIGIBILITY_VERSION,
            eligibility_snapshot=sanitize_for_log(snap),
            expires_at=expires_at,
            created_by=actor,
            reason=reason[:500],
            correlation_id=correlation_id or str(uuid.uuid4())[:64],
        )
        self._session.add(row)
        self._session.flush()

        self._history(
            row.queue_id,
            action="CREATED",
            actor=actor,
            new="DRAFT",
            reason=reason,
            correlation_id=correlation_id,
        )

        return {
            "idempotent_replay": False,
            "queue": self._public(row),
            "eligibility": eligibility,
        }

    def queue(
        self,
        queue_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """DRAFT → QUEUED (create 와 분리)."""
        row = self._get_queue(queue_id)
        if row.queue_status != "DRAFT":
            raise AIRecommendationQueueError(
                "INVALID_STATE", f"expected DRAFT got {row.queue_status}"
            )

        eligibility = self.validate(
            source_type=row.source_type,
            candidate_assessment_id=row.candidate_assessment_id,
            candidate_consensus_id=row.candidate_consensus_id,
            allow_existing_candidate_override=True,
            override_reason="queue_revalidation",
        )
        if not eligibility.get("allowed"):
            raise AIRecommendationQueueError(
                "NOT_ELIGIBLE",
                ",".join(eligibility.get("reasons") or []),
            )

        stale = self._staleness.check(
            source_type=row.source_type,
            candidate_assessment_id=row.candidate_assessment_id,
            candidate_consensus_id=row.candidate_consensus_id,
            stored_source_result_hash=row.source_result_hash,
            stored_evidence_bundle_hash=row.evidence_bundle_hash,
        )
        if stale.get("stale"):
            raise AIRecommendationQueueError(
                "SOURCE_STALE",
                ",".join(stale.get("reasons") or []),
            )

        if is_expired(expires_at=row.expires_at):
            self._transition(
                row,
                new_status="EXPIRED",
                actor=actor,
                action="EXPIRED_ON_QUEUE",
                reason="expired before queue",
            )
            raise AIRecommendationQueueError("EXPIRED", "queue expired")

        row.eligibility_snapshot = sanitize_for_log(eligibility.get("snapshot"))
        self._transition(
            row,
            new_status="QUEUED",
            actor=actor,
            action="QUEUED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"queue": self._public(row)}

    def assign(
        self,
        queue_id: int,
        *,
        actor: str,
        assignee_id: str,
        reason: str,
        due_at: datetime | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_queue(queue_id)
        if row.queue_status not in {"QUEUED", "ASSIGNED", "MORE_INFORMATION_REQUIRED"}:
            raise AIRecommendationQueueError(
                "INVALID_STATE", f"cannot assign from {row.queue_status}"
            )

        active = self._active_assignment(queue_id)
        if active is not None:
            active.assignment_status = "CANCELLED"
            active.cancelled_at = _now()

        assignment = AICandidateRecommendationAssignmentEntity(
            queue_id=queue_id,
            assignee_id=assignee_id,
            assignment_status="ACTIVE",
            assigned_by=actor,
            due_at=due_at,
        )
        self._session.add(assignment)

        row.assigned_to = assignee_id
        row.assigned_at = _now()
        self._transition(
            row,
            new_status="ASSIGNED",
            actor=actor,
            action="ASSIGNED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"queue": self._public(row), "assignment_id": assignment.assignment_id}

    def reassign(
        self,
        queue_id: int,
        *,
        actor: str,
        assignee_id: str,
        reason: str,
        due_at: datetime | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        return self.assign(
            queue_id,
            actor=actor,
            assignee_id=assignee_id,
            reason=reason,
            due_at=due_at,
            correlation_id=correlation_id,
        )

    def start_review(
        self,
        queue_id: int,
        *,
        actor: str,
        reviewer_id: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_queue(queue_id)
        if row.queue_status not in {"ASSIGNED", "UNDER_REVIEW", "MORE_INFORMATION_REQUIRED"}:
            raise AIRecommendationQueueError(
                "INVALID_STATE", f"cannot start review from {row.queue_status}"
            )

        max_version = self._session.scalar(
            select(func.max(AICandidateRecommendationReviewEntity.review_version)).where(
                AICandidateRecommendationReviewEntity.queue_id == queue_id
            )
        ) or 0

        review = AICandidateRecommendationReviewEntity(
            queue_id=queue_id,
            review_version=int(max_version) + 1,
            review_status="DRAFT",
            reviewer_id=reviewer_id,
            recommendation_scope="CONSIDERATION_ONLY",
        )
        self._session.add(review)
        row.review_started_at = _now()
        self._transition(
            row,
            new_status="UNDER_REVIEW",
            actor=actor,
            action="REVIEW_STARTED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"queue": self._public(row), "review": self._public_review(review)}

    def submit_review(
        self,
        review_id: int,
        *,
        actor: str,
        summary: str | None = None,
        eligibility_score: float,
        analytical_quality_score: float,
        evidence_quality_score: float,
        risk_awareness_score: float,
        consistency_score: float,
        safety_score: float,
        recommendation_scope: str = "CONSIDERATION_ONLY",
        findings: list[dict[str, Any]] | None = None,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        review = self._session.get(AICandidateRecommendationReviewEntity, review_id)
        if review is None:
            raise AIRecommendationQueueError("NOT_FOUND", "review missing")
        if review.review_status != "DRAFT":
            raise AIRecommendationQueueError(
                "INVALID_STATE", f"review status {review.review_status}"
            )
        if recommendation_scope not in RECOMMENDATION_SCOPES:
            raise AIRecommendationQueueError(
                "INVALID_SCOPE", recommendation_scope
            )

        overall = compute_overall_score(
            eligibility_score=validate_optional_score(eligibility_score),
            analytical_quality_score=validate_optional_score(
                analytical_quality_score
            ),
            evidence_quality_score=validate_optional_score(evidence_quality_score),
            risk_awareness_score=validate_optional_score(risk_awareness_score),
            consistency_score=validate_optional_score(consistency_score),
            safety_score=validate_optional_score(safety_score),
        )

        review.summary = summary
        review.eligibility_score = eligibility_score
        review.analytical_quality_score = analytical_quality_score
        review.evidence_quality_score = evidence_quality_score
        review.risk_awareness_score = risk_awareness_score
        review.consistency_score = consistency_score
        review.safety_score = safety_score
        review.overall_score = overall
        review.recommendation_scope = recommendation_scope
        review.review_status = "SUBMITTED"
        review.submitted_at = _now()

        for item in findings or []:
            ftype = str(item.get("finding_type") or "OTHER")
            severity = str(item.get("severity") or "INFO")
            if ftype not in FINDING_TYPES:
                raise AIRecommendationQueueError("INVALID_FINDING_TYPE", ftype)
            if severity not in SEVERITIES:
                raise AIRecommendationQueueError("INVALID_SEVERITY", severity)
            self._session.add(
                AICandidateRecommendationFindingEntity(
                    review_id=review.review_id,
                    finding_type=ftype,
                    severity=severity,
                    field_path=item.get("field_path"),
                    description_sanitized=str(
                        item.get("description") or item.get("description_sanitized") or ""
                    )[:2000],
                    requires_resolution=bool(item.get("requires_resolution")),
                    resolution_status="OPEN",
                )
            )

        row = self._get_queue(review.queue_id)
        self._transition(
            row,
            new_status="UNDER_REVIEW",
            actor=actor,
            action="UNDER_REVIEW",
            reason=reason,
            correlation_id=correlation_id,
        )

        assignment = self._active_assignment(review.queue_id)
        if assignment is not None:
            assignment.assignment_status = "COMPLETED"
            assignment.completed_at = _now()

        return {"review": self._public_review(review), "queue": self._public(row)}

    def amend_review(
        self,
        review_id: int,
        *,
        actor: str,
        amendment_reason: str,
        summary: str | None = None,
        eligibility_score: float | None = None,
        analytical_quality_score: float | None = None,
        evidence_quality_score: float | None = None,
        risk_awareness_score: float | None = None,
        consistency_score: float | None = None,
        safety_score: float | None = None,
        findings: list[dict[str, Any]] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        original = self._session.get(AICandidateRecommendationReviewEntity, review_id)
        if original is None:
            raise AIRecommendationQueueError("NOT_FOUND", "review missing")
        if original.review_status not in {"SUBMITTED", "AMENDED"}:
            raise AIRecommendationQueueError(
                "INVALID_STATE", "only submitted reviews can be amended"
            )

        max_version = self._session.scalar(
            select(func.max(AICandidateRecommendationReviewEntity.review_version)).where(
                AICandidateRecommendationReviewEntity.queue_id == original.queue_id
            )
        ) or 0

        new_review = AICandidateRecommendationReviewEntity(
            queue_id=original.queue_id,
            review_version=int(max_version) + 1,
            review_status="DRAFT",
            reviewer_id=original.reviewer_id,
            summary=summary if summary is not None else original.summary,
            eligibility_score=(
                eligibility_score
                if eligibility_score is not None
                else original.eligibility_score
            ),
            analytical_quality_score=(
                analytical_quality_score
                if analytical_quality_score is not None
                else original.analytical_quality_score
            ),
            evidence_quality_score=(
                evidence_quality_score
                if evidence_quality_score is not None
                else original.evidence_quality_score
            ),
            risk_awareness_score=(
                risk_awareness_score
                if risk_awareness_score is not None
                else original.risk_awareness_score
            ),
            consistency_score=(
                consistency_score
                if consistency_score is not None
                else original.consistency_score
            ),
            safety_score=(
                safety_score if safety_score is not None else original.safety_score
            ),
            recommendation_scope=original.recommendation_scope,
            amended_from_id=original.review_id,
            amendment_reason=amendment_reason[:500],
        )
        self._session.add(new_review)
        self._session.flush()

        return self.submit_review(
            new_review.review_id,
            actor=actor,
            summary=new_review.summary,
            eligibility_score=float(new_review.eligibility_score or 0),
            analytical_quality_score=float(new_review.analytical_quality_score or 0),
            evidence_quality_score=float(new_review.evidence_quality_score or 0),
            risk_awareness_score=float(new_review.risk_awareness_score or 0),
            consistency_score=float(new_review.consistency_score or 0),
            safety_score=float(new_review.safety_score or 0),
            recommendation_scope=new_review.recommendation_scope,
            findings=findings,
            reason=amendment_reason,
            correlation_id=correlation_id,
        )

    def withdraw_review(
        self,
        review_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        review = self._session.get(AICandidateRecommendationReviewEntity, review_id)
        if review is None:
            raise AIRecommendationQueueError("NOT_FOUND", "review missing")
        if review.review_status not in REVIEW_STATUS:
            raise AIRecommendationQueueError("INVALID_STATE", "bad review status")

        review.review_status = "WITHDRAWN"
        row = self._get_queue(review.queue_id)
        self._transition(
            row,
            new_status="ASSIGNED",
            actor=actor,
            action="REVIEW_WITHDRAWN",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"review": self._public_review(review), "queue": self._public(row)}

    def decide(
        self,
        queue_id: int,
        *,
        actor: str,
        decision: str,
        decision_reason: str,
        manager_override: bool = False,
        override_reason: str | None = None,
        warning_conditions: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        최종 결정 — APPROVED_FOR_CONSIDERATION ≠ candidate registration.
        Self-approval blocked; critical findings block even with override.
        """
        if decision not in DECISION:
            raise AIRecommendationQueueError("INVALID_DECISION", decision)

        row = self._get_queue(queue_id)
        if row.queue_status in TERMINAL_QUEUE_STATUSES:
            raise AIRecommendationQueueError(
                "INVALID_STATE", f"terminal status {row.queue_status}"
            )
        if row.queue_status not in {
            "UNDER_REVIEW",
            "ON_HOLD",
            "MORE_INFORMATION_REQUIRED",
        }:
            raise AIRecommendationQueueError(
                "INVALID_STATE", f"cannot decide from {row.queue_status}"
            )

        if is_expired(row.expires_at):
            raise AIRecommendationQueueError(
                "EXPIRED", "만료된 Queue는 승인할 수 없습니다"
            )

        # Decision 직전 Source Hash 재검증
        stale = self._staleness.check(
            source_type=row.source_type,
            candidate_assessment_id=row.candidate_assessment_id,
            candidate_consensus_id=row.candidate_consensus_id,
            stored_source_result_hash=row.source_result_hash,
            stored_evidence_bundle_hash=row.evidence_bundle_hash,
        )
        if stale.get("stale") and decision in {
            "APPROVED_FOR_CONSIDERATION",
            "APPROVED_WITH_WARNINGS",
        }:
            raise AIRecommendationQueueError(
                "SOURCE_CHANGED",
                ",".join(stale.get("reasons") or ["source changed"]),
            )

        if row.created_by == actor and not manager_override:
            raise AIRecommendationQueueError(
                "SELF_APPROVAL_BLOCKED",
                "creator cannot decide without manager_override",
            )

        critical_count, unresolved_high = self._finding_counts(queue_id)

        # Core Safety: Critical findings → never approve even with override
        if critical_count > 0 and decision in {
            "APPROVED_FOR_CONSIDERATION",
            "APPROVED_WITH_WARNINGS",
        }:
            raise AIRecommendationQueueError(
                "CRITICAL_FINDINGS_BLOCK",
                f"{critical_count} critical findings — approval blocked",
            )

        if (
            unresolved_high > 0
            and decision == "APPROVED_FOR_CONSIDERATION"
            and not manager_override
        ):
            raise AIRecommendationQueueError(
                "HIGH_FINDINGS_BLOCK",
                "unresolved HIGH findings — use APPROVED_WITH_WARNINGS or resolve",
            )

        if manager_override and not override_reason:
            raise AIRecommendationQueueError(
                "OVERRIDE_REASON_REQUIRED", "manager override needs reason"
            )

        max_version = self._session.scalar(
            select(
                func.max(AICandidateRecommendationDecisionEntity.decision_version)
            ).where(
                AICandidateRecommendationDecisionEntity.queue_id == queue_id
            )
        ) or 0

        decision_row = AICandidateRecommendationDecisionEntity(
            queue_id=queue_id,
            decision_version=int(max_version) + 1,
            decision=decision,
            decision_reason=decision_reason[:500],
            warning_conditions=sanitize_for_log(warning_conditions or {}),
            decided_by=actor,
            manager_override=manager_override,
            override_reason=override_reason[:500] if override_reason else None,
            source_result_hash_at_decision=row.source_result_hash,
            evidence_bundle_hash_at_decision=row.evidence_bundle_hash,
            source_review_decision_at_decision=row.source_review_decision,
            analytical_score_at_decision=row.analytical_score,
            risk_score_at_decision=row.risk_score,
            confidence_at_decision=row.confidence,
            agreement_level_at_decision=row.agreement_level,
            disagreement_level_at_decision=row.disagreement_level,
            critical_findings_count=critical_count,
            unresolved_high_findings_count=unresolved_high,
            eligibility_version=row.eligibility_version,
            review_formula_version=REVIEW_FORMULA_VERSION,
            expires_at=row.expires_at,
        )
        self._session.add(decision_row)

        status_map = {
            "APPROVED_FOR_CONSIDERATION": "APPROVED_FOR_CONSIDERATION",
            "APPROVED_WITH_WARNINGS": "APPROVED_WITH_WARNINGS",
            "REJECTED": "REJECTED",
            "MORE_INFORMATION_REQUIRED": "MORE_INFORMATION_REQUIRED",
            "ON_HOLD": "ON_HOLD",
            "NOT_ELIGIBLE": "NOT_ELIGIBLE",
            "WITHDRAWN": "WITHDRAWN",
            "EXPIRED": "EXPIRED",
        }
        new_status = status_map.get(decision, "UNDER_REVIEW")
        row.decided_at = _now()
        self._transition(
            row,
            new_status=new_status,
            actor=actor,
            action="DECIDED",
            reason=decision_reason,
            correlation_id=correlation_id,
        )

        return {
            "queue": self._public(row),
            "decision": self._public_decision(decision_row),
        }

    def hold(
        self,
        queue_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_queue(queue_id)
        if row.queue_status in TERMINAL_QUEUE_STATUSES:
            raise AIRecommendationQueueError("INVALID_STATE", "terminal")
        self._transition(
            row,
            new_status="ON_HOLD",
            actor=actor,
            action="HELD",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"queue": self._public(row)}

    def resume(
        self,
        queue_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_queue(queue_id)
        if row.queue_status not in {"ON_HOLD", "MORE_INFORMATION_REQUIRED"}:
            raise AIRecommendationQueueError(
                "INVALID_STATE", f"cannot resume from {row.queue_status}"
            )
        target = (
            "UNDER_REVIEW"
            if self._latest_submitted_reviews(queue_id)
            else "ASSIGNED"
        )
        self._transition(
            row,
            new_status=target,
            actor=actor,
            action="RESUMED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"queue": self._public(row)}

    def request_more_information(
        self,
        queue_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_queue(queue_id)
        self._transition(
            row,
            new_status="MORE_INFORMATION_REQUIRED",
            actor=actor,
            action="MORE_INFORMATION_REQUIRED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"queue": self._public(row)}

    def withdraw(
        self,
        queue_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_queue(queue_id)
        if row.queue_status in TERMINAL_QUEUE_STATUSES:
            raise AIRecommendationQueueError("INVALID_STATE", "already terminal")
        self._transition(
            row,
            new_status="WITHDRAWN",
            actor=actor,
            action="WITHDRAWN",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"queue": self._public(row)}

    def expire(
        self,
        queue_id: int,
        *,
        actor: str,
        reason: str = "manual expire",
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_queue(queue_id)
        if row.queue_status in TERMINAL_QUEUE_STATUSES:
            raise AIRecommendationQueueError("INVALID_STATE", "already terminal")
        self._transition(
            row,
            new_status="EXPIRED",
            actor=actor,
            action="EXPIRED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"queue": self._public(row)}

    def revalidate(
        self,
        queue_id: int,
        *,
        actor: str,
        allow_existing_candidate_override: bool = False,
        override_reason: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_queue(queue_id)
        eligibility = self.validate(
            source_type=row.source_type,
            candidate_assessment_id=row.candidate_assessment_id,
            candidate_consensus_id=row.candidate_consensus_id,
            allow_existing_candidate_override=allow_existing_candidate_override,
            override_reason=override_reason,
        )
        stale = self._staleness.check(
            source_type=row.source_type,
            candidate_assessment_id=row.candidate_assessment_id,
            candidate_consensus_id=row.candidate_consensus_id,
            stored_source_result_hash=row.source_result_hash,
            stored_evidence_bundle_hash=row.evidence_bundle_hash,
        )
        row.eligibility_snapshot = sanitize_for_log(eligibility.get("snapshot"))
        self._history(
            row.queue_id,
            action="REVALIDATED",
            actor=actor,
            previous=row.queue_status,
            new=row.queue_status,
            reason="revalidation",
            correlation_id=correlation_id,
        )
        return {
            "queue": self._public(row),
            "eligibility": eligibility,
            "staleness": stale,
        }

    def requeue(
        self,
        queue_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_queue(queue_id)
        if row.queue_status not in {"EXPIRED", "REJECTED", "WITHDRAWN"}:
            raise AIRecommendationQueueError(
                "INVALID_STATE", f"cannot requeue from {row.queue_status}"
            )

        revalidation = self.revalidate(
            queue_id,
            actor=actor,
            allow_existing_candidate_override=True,
            override_reason=reason,
            correlation_id=correlation_id,
        )
        if not revalidation["eligibility"].get("allowed"):
            raise AIRecommendationQueueError(
                "NOT_ELIGIBLE",
                ",".join(revalidation["eligibility"].get("reasons") or []),
            )

        row.expires_at = compute_expires_at(market_type=row.market_type)
        self._transition(
            row,
            new_status="QUEUED",
            actor=actor,
            action="REQUEUED",
            reason=reason,
            correlation_id=correlation_id,
        )
        return {"queue": self._public(row)}

    def list_queues(
        self,
        *,
        queue_status: str | None = None,
        market_type: str | None = None,
        symbol: str | None = None,
        assigned_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        stmt = select(AICandidateRecommendationQueueEntity).order_by(
            AICandidateRecommendationQueueEntity.created_at.desc()
        )
        if queue_status:
            stmt = stmt.where(
                AICandidateRecommendationQueueEntity.queue_status == queue_status
            )
        if market_type:
            stmt = stmt.where(
                AICandidateRecommendationQueueEntity.market_type == market_type
            )
        if symbol:
            stmt = stmt.where(AICandidateRecommendationQueueEntity.symbol == symbol)
        if assigned_to:
            stmt = stmt.where(
                AICandidateRecommendationQueueEntity.assigned_to == assigned_to
            )
        rows = list(
            self._session.scalars(stmt.limit(limit).offset(offset)).all()
        )
        return {
            "items": [self._public(r) for r in rows],
            "limit": limit,
            "offset": offset,
        }

    def get(self, queue_id: int) -> dict[str, Any]:
        return {"queue": self._public(self._get_queue(queue_id))}

    def get_reviews(self, queue_id: int) -> dict[str, Any]:
        self._get_queue(queue_id)
        rows = list(
            self._session.scalars(
                select(AICandidateRecommendationReviewEntity)
                .where(AICandidateRecommendationReviewEntity.queue_id == queue_id)
                .order_by(AICandidateRecommendationReviewEntity.review_version)
            ).all()
        )
        return {"items": [self._public_review(r) for r in rows]}

    def get_findings(self, queue_id: int) -> dict[str, Any]:
        reviews = self.get_reviews(queue_id)["items"]
        review_ids = [r["id"] for r in reviews]
        if not review_ids:
            return {"items": []}
        rows = list(
            self._session.scalars(
                select(AICandidateRecommendationFindingEntity).where(
                    AICandidateRecommendationFindingEntity.review_id.in_(
                        review_ids
                    )
                )
            ).all()
        )
        return {"items": [self._public_finding(r) for r in rows]}

    def get_decisions(self, queue_id: int) -> dict[str, Any]:
        self._get_queue(queue_id)
        rows = list(
            self._session.scalars(
                select(AICandidateRecommendationDecisionEntity)
                .where(
                    AICandidateRecommendationDecisionEntity.queue_id == queue_id
                )
                .order_by(
                    AICandidateRecommendationDecisionEntity.decision_version
                )
            ).all()
        )
        return {"items": [self._public_decision(r) for r in rows]}

    def get_history(self, queue_id: int) -> dict[str, Any]:
        self._get_queue(queue_id)
        rows = list(
            self._session.scalars(
                select(AICandidateRecommendationHistoryEntity)
                .where(
                    AICandidateRecommendationHistoryEntity.queue_id == queue_id
                )
                .order_by(AICandidateRecommendationHistoryEntity.created_at)
            ).all()
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

    def compare(self, queue_id: int, other_queue_id: int) -> dict[str, Any]:
        a = self._get_queue(queue_id)
        b = self._get_queue(other_queue_id)
        return {
            "queue_a": self._public(a),
            "queue_b": self._public(b),
            "same_symbol": a.symbol == b.symbol and a.exchange_code == b.exchange_code,
            "same_source_hash": a.source_result_hash == b.source_result_hash,
            "score_delta": {
                "analytical": (a.analytical_score or 0) - (b.analytical_score or 0),
                "risk": (a.risk_score or 0) - (b.risk_score or 0),
                "confidence": (a.confidence or 0) - (b.confidence or 0),
            },
        }

    def get_source(self, queue_id: int) -> dict[str, Any]:
        row = self._get_queue(queue_id)
        if row.source_type == "CANDIDATE_ASSESSMENT":
            from stock_platform.ai.candidate_assessment.entities import (
                AICandidateAssessmentEntity,
            )

            source = self._session.get(
                AICandidateAssessmentEntity, row.candidate_assessment_id
            )
            if source is None:
                raise AIRecommendationQueueError("SOURCE_NOT_FOUND", "assessment")
            return {
                "source_type": row.source_type,
                "assessment_id": source.assessment_id,
                "status": source.assessment_status,
                "symbol": source.symbol,
                "result_hash": source.result_hash,
                "safe_result": source.safe_result,
            }
        from stock_platform.ai.candidate_consensus.entities import (
            AICandidateConsensusEntity,
        )

        source = self._session.get(
            AICandidateConsensusEntity, row.candidate_consensus_id
        )
        if source is None:
            raise AIRecommendationQueueError("SOURCE_NOT_FOUND", "consensus")
        return {
            "source_type": row.source_type,
            "consensus_id": source.consensus_id,
            "status": source.consensus_status,
            "symbol": source.symbol,
            "result_hash": source.result_hash,
            "safe_result": source.safe_result,
        }

    def dashboard_summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for status in QUEUE_STATUS:
            count = self._session.scalar(
                select(func.count()).select_from(
                    AICandidateRecommendationQueueEntity
                ).where(
                    AICandidateRecommendationQueueEntity.queue_status == status
                )
            )
            counts[status] = int(count or 0)

        expiring_soon = self._session.scalar(
            select(func.count()).select_from(
                AICandidateRecommendationQueueEntity
            ).where(
                AICandidateRecommendationQueueEntity.queue_status.notin_(
                    list(TERMINAL_QUEUE_STATUSES)
                ),
                AICandidateRecommendationQueueEntity.expires_at <= compute_expires_at(
                    market_type="STOCK", requested_hours=6
                ),
            )
        )

        return {
            "status_counts": counts,
            "expiring_within_6h": int(expiring_soon or 0),
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def promotion_eligibility_snapshot(self, queue_id: int) -> dict[str, Any]:
        row = self._get_queue(queue_id)
        decisions = self.get_decisions(queue_id)["items"]
        latest_decision = decisions[-1]["decision"] if decisions else None
        reviews = self._latest_submitted_reviews(queue_id)
        review_dicts = [
            {
                "overall_score": r.overall_score,
                "safety_score": r.safety_score,
            }
            for r in reviews
        ]
        critical, unresolved_high = self._finding_counts(queue_id)
        stale = self._staleness.check(
            source_type=row.source_type,
            candidate_assessment_id=row.candidate_assessment_id,
            candidate_consensus_id=row.candidate_consensus_id,
            stored_source_result_hash=row.source_result_hash,
            stored_evidence_bundle_hash=row.evidence_bundle_hash,
        )
        snap = row.eligibility_snapshot or {}
        return build_promotion_eligibility_snapshot(
            queue_status=row.queue_status,
            latest_decision=latest_decision,
            submitted_reviews=review_dicts,
            critical_findings_count=critical,
            unresolved_high_findings_count=unresolved_high,
            stale=bool(stale.get("stale")),
            expired=is_expired(expires_at=row.expires_at),
            existing_candidate_conflict=bool(snap.get("existing_candidate")),
        )
