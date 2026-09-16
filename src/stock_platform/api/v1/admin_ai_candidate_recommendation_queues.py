"""STEP 11-11 — Admin AI Candidate Recommendation Queue API (검토 큐, 매매·후보등록 아님)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_recommendation_queue.batch_service import (
    AIRecommendationQueueBatchService,
)
from stock_platform.ai.candidate_recommendation_queue.service import (
    AIRecommendationQueueError,
    AIRecommendationQueueService,
)
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/ai/candidate-recommendation-queues",
    tags=["Admin AI Candidate Recommendation Queues"],
    dependencies=[Depends(require_admin)],
)


class CreateBody(BaseModel):
    source_type: str
    candidate_assessment_id: int | None = None
    candidate_consensus_id: int | None = None
    priority: str = "NORMAL"
    allow_existing_candidate_override: bool = False
    override_reason: str | None = None
    expiry_hours: float | None = None
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)
    correlation_id: str | None = None


class ValidateBody(BaseModel):
    source_type: str
    candidate_assessment_id: int | None = None
    candidate_consensus_id: int | None = None
    allow_existing_candidate_override: bool = False
    override_reason: str | None = None


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AssignBody(BaseModel):
    assignee_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)
    due_at: datetime | None = None
    correlation_id: str | None = None


class StartReviewBody(BaseModel):
    reviewer_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)
    correlation_id: str | None = None


class SubmitReviewBody(BaseModel):
    summary: str | None = None
    eligibility_score: float
    analytical_quality_score: float
    evidence_quality_score: float
    risk_awareness_score: float
    consistency_score: float
    safety_score: float
    recommendation_scope: str = "CONSIDERATION_ONLY"
    findings: list[dict[str, Any]] | None = None
    reason: str = Field(min_length=1, max_length=500)
    correlation_id: str | None = None


class AmendReviewBody(BaseModel):
    amendment_reason: str = Field(min_length=1, max_length=500)
    summary: str | None = None
    eligibility_score: float | None = None
    analytical_quality_score: float | None = None
    evidence_quality_score: float | None = None
    risk_awareness_score: float | None = None
    consistency_score: float | None = None
    safety_score: float | None = None
    findings: list[dict[str, Any]] | None = None
    correlation_id: str | None = None


class DecideBody(BaseModel):
    decision: str
    decision_reason: str = Field(min_length=1, max_length=500)
    manager_override: bool = False
    override_reason: str | None = None
    warning_conditions: dict[str, Any] | None = None
    correlation_id: str | None = None


class RevalidateBody(BaseModel):
    allow_existing_candidate_override: bool = False
    override_reason: str | None = None
    correlation_id: str | None = None


class BatchBody(BaseModel):
    sources: list[dict[str, Any]] = Field(min_length=1)
    priority: str = "NORMAL"
    auto_queue: bool = False
    allow_existing_candidate_override: bool = False
    override_reason: str | None = None
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)


class CompareBody(BaseModel):
    left_id: int
    right_id: int


def _audit(session: Session, *, event_type: str, actor: str, detail: dict) -> None:
    try:
        AuditLogService(session).record(
            event_type=event_type,
            actor=actor,
            detail=sanitize_for_log(detail),
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _raise(exc: AIRecommendationQueueError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    if exc.code in {
        "NOT_ELIGIBLE",
        "SELF_APPROVAL_BLOCKED",
        "CRITICAL_FINDINGS_BLOCK",
        "HIGH_FINDINGS_BLOCK",
        "SOURCE_STALE",
        "SOURCE_CHANGED",
        "DUPLICATE_ACTIVE_QUEUE",
        "EXPIRED",
        "OVERRIDE_REASON_REQUIRED",
    }:
        code = status.HTTP_403_FORBIDDEN
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.get("")
def list_queues(
    queue_status: str | None = None,
    market_type: str | None = None,
    symbol: str | None = None,
    assigned_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    result = AIRecommendationQueueService(session).list_queues(
        queue_status=queue_status,
        market_type=market_type,
        symbol=symbol,
        assigned_to=assigned_to,
        limit=limit,
        offset=offset,
    )
    items = result.get("items") or []
    return {"count": len(items), **result}


@router.get("/dashboard")
def dashboard(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AIRecommendationQueueService(session).dashboard_summary()


@router.post("/validate")
def validate_source(
    body: ValidateBody,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AIRecommendationQueueService(session).validate(
            source_type=body.source_type,
            candidate_assessment_id=body.candidate_assessment_id,
            candidate_consensus_id=body.candidate_consensus_id,
            allow_existing_candidate_override=body.allow_existing_candidate_override,
            override_reason=body.override_reason,
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("")
def create_queue(
    body: CreateBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).create(
            actor=actor,
            reason=body.reason,
            source_type=body.source_type,
            candidate_assessment_id=body.candidate_assessment_id,
            candidate_consensus_id=body.candidate_consensus_id,
            priority=body.priority,
            allow_existing_candidate_override=body.allow_existing_candidate_override,
            override_reason=body.override_reason,
            expiry_hours=body.expiry_hours,
            idempotency_key=body.idempotency_key,
            correlation_id=body.correlation_id,
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_CREATED",
        actor=actor,
        detail={
            "queue_id": result["queue"]["id"],
            "source_type": body.source_type,
            "idempotent_replay": result.get("idempotent_replay"),
        },
    )
    return result


@router.post("/batches")
def create_batch(
    body: BatchBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueBatchService(session).create_batch(
            actor=actor,
            reason=body.reason,
            sources=body.sources,
            priority=body.priority,
            auto_queue=body.auto_queue,
            allow_existing_candidate_override=body.allow_existing_candidate_override,
            override_reason=body.override_reason,
            idempotency_key=body.idempotency_key,
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_BATCH_CREATED",
        actor=actor,
        detail={
            "created_count": result.get("created_count"),
            "error_count": result.get("error_count"),
            "auto_queue": body.auto_queue,
        },
    )
    return result


@router.post("/compare")
def compare_queues(
    body: CompareBody,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AIRecommendationQueueService(session).compare(
            body.left_id, body.right_id
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{queue_id}")
def get_queue(
    queue_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AIRecommendationQueueService(session).get(queue_id)
    except AIRecommendationQueueError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{queue_id}/reviews")
def get_reviews(
    queue_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        result = AIRecommendationQueueService(session).get_reviews(queue_id)
    except AIRecommendationQueueError as exc:
        _raise(exc)
    items = result.get("items") or []
    return {"count": len(items), **result}


@router.get("/{queue_id}/findings")
def get_findings(
    queue_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        result = AIRecommendationQueueService(session).get_findings(queue_id)
    except AIRecommendationQueueError as exc:
        _raise(exc)
    items = result.get("items") or []
    return {"count": len(items), **result}


@router.get("/{queue_id}/decisions")
def get_decisions(
    queue_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        result = AIRecommendationQueueService(session).get_decisions(queue_id)
    except AIRecommendationQueueError as exc:
        _raise(exc)
    items = result.get("items") or []
    return {"count": len(items), **result}


@router.get("/{queue_id}/history")
def get_history(
    queue_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        result = AIRecommendationQueueService(session).get_history(queue_id)
    except AIRecommendationQueueError as exc:
        _raise(exc)
    items = result.get("items") or []
    return {"count": len(items), **result}


@router.get("/{queue_id}/source")
def get_source(
    queue_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AIRecommendationQueueService(session).get_source(queue_id)
    except AIRecommendationQueueError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{queue_id}/promotion-eligibility")
def promotion_eligibility(
    queue_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AIRecommendationQueueService(session).promotion_eligibility_snapshot(
            queue_id
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/{queue_id}/queue")
def enqueue(
    queue_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).queue(
            queue_id, actor=actor, reason=body.reason
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_ENQUEUED",
        actor=actor,
        detail={"queue_id": queue_id, "reason": body.reason},
    )
    return result


@router.post("/{queue_id}/assign")
def assign(
    queue_id: int,
    body: AssignBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).assign(
            queue_id,
            actor=actor,
            assignee_id=body.assignee_id,
            reason=body.reason,
            due_at=body.due_at,
            correlation_id=body.correlation_id,
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_ASSIGNED",
        actor=actor,
        detail={
            "queue_id": queue_id,
            "assignee_id": body.assignee_id,
            "reason": body.reason,
        },
    )
    return result


@router.post("/{queue_id}/reassign")
def reassign(
    queue_id: int,
    body: AssignBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).reassign(
            queue_id,
            actor=actor,
            assignee_id=body.assignee_id,
            reason=body.reason,
            due_at=body.due_at,
            correlation_id=body.correlation_id,
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_REASSIGNED",
        actor=actor,
        detail={
            "queue_id": queue_id,
            "assignee_id": body.assignee_id,
            "reason": body.reason,
        },
    )
    return result


@router.post("/{queue_id}/start-review")
def start_review(
    queue_id: int,
    body: StartReviewBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).start_review(
            queue_id,
            actor=actor,
            reviewer_id=body.reviewer_id,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_REVIEW_STARTED",
        actor=actor,
        detail={
            "queue_id": queue_id,
            "reviewer_id": body.reviewer_id,
            "reason": body.reason,
        },
    )
    return result


@router.post("/reviews/{review_id}/submit")
def submit_review(
    review_id: int,
    body: SubmitReviewBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).submit_review(
            review_id,
            actor=actor,
            summary=body.summary,
            eligibility_score=body.eligibility_score,
            analytical_quality_score=body.analytical_quality_score,
            evidence_quality_score=body.evidence_quality_score,
            risk_awareness_score=body.risk_awareness_score,
            consistency_score=body.consistency_score,
            safety_score=body.safety_score,
            recommendation_scope=body.recommendation_scope,
            findings=body.findings,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_REVIEW_SUBMITTED",
        actor=actor,
        detail={
            "review_id": review_id,
            "queue_id": result["queue"]["id"],
            "overall_score": result["review"].get("overall_score"),
        },
    )
    return result


@router.post("/reviews/{review_id}/amend")
def amend_review(
    review_id: int,
    body: AmendReviewBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).amend_review(
            review_id,
            actor=actor,
            amendment_reason=body.amendment_reason,
            summary=body.summary,
            eligibility_score=body.eligibility_score,
            analytical_quality_score=body.analytical_quality_score,
            evidence_quality_score=body.evidence_quality_score,
            risk_awareness_score=body.risk_awareness_score,
            consistency_score=body.consistency_score,
            safety_score=body.safety_score,
            findings=body.findings,
            correlation_id=body.correlation_id,
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_REVIEW_AMENDED",
        actor=actor,
        detail={"review_id": review_id, "queue_id": result["queue"]["id"]},
    )
    return result


@router.post("/reviews/{review_id}/withdraw")
def withdraw_review(
    review_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).withdraw_review(
            review_id,
            actor=actor,
            reason=body.reason,
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_REVIEW_WITHDRAWN",
        actor=actor,
        detail={"review_id": review_id, "reason": body.reason},
    )
    return result


@router.post("/{queue_id}/decide")
def decide(
    queue_id: int,
    body: DecideBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).decide(
            queue_id,
            actor=actor,
            decision=body.decision,
            decision_reason=body.decision_reason,
            manager_override=body.manager_override,
            override_reason=body.override_reason,
            warning_conditions=body.warning_conditions,
            correlation_id=body.correlation_id,
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_DECIDED",
        actor=actor,
        detail={
            "queue_id": queue_id,
            "decision": body.decision,
            "manager_override": body.manager_override,
        },
    )
    return result


@router.post("/{queue_id}/hold")
def hold(
    queue_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).hold(
            queue_id, actor=actor, reason=body.reason
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_HELD",
        actor=actor,
        detail={"queue_id": queue_id, "reason": body.reason},
    )
    return result


@router.post("/{queue_id}/resume")
def resume(
    queue_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).resume(
            queue_id, actor=actor, reason=body.reason
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_RESUMED",
        actor=actor,
        detail={"queue_id": queue_id, "reason": body.reason},
    )
    return result


@router.post("/{queue_id}/request-more-information")
def request_more_information(
    queue_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).request_more_information(
            queue_id, actor=actor, reason=body.reason
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_MORE_INFO",
        actor=actor,
        detail={"queue_id": queue_id, "reason": body.reason},
    )
    return result


@router.post("/{queue_id}/withdraw")
def withdraw_queue(
    queue_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).withdraw(
            queue_id, actor=actor, reason=body.reason
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_WITHDRAWN",
        actor=actor,
        detail={"queue_id": queue_id, "reason": body.reason},
    )
    return result


@router.post("/{queue_id}/expire")
def expire_queue(
    queue_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).expire(
            queue_id, actor=actor, reason=body.reason
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_EXPIRED",
        actor=actor,
        detail={"queue_id": queue_id, "reason": body.reason},
    )
    return result


@router.post("/{queue_id}/revalidate")
def revalidate(
    queue_id: int,
    body: RevalidateBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).revalidate(
            queue_id,
            actor=actor,
            allow_existing_candidate_override=body.allow_existing_candidate_override,
            override_reason=body.override_reason,
            correlation_id=body.correlation_id,
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_REVALIDATED",
        actor=actor,
        detail={"queue_id": queue_id},
    )
    return result


@router.post("/{queue_id}/requeue")
def requeue(
    queue_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIRecommendationQueueService(session).requeue(
            queue_id, actor=actor, reason=body.reason
        )
    except AIRecommendationQueueError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_QUEUE_REQUEUED",
        actor=actor,
        detail={"queue_id": queue_id, "reason": body.reason},
    )
    return result
