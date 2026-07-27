"""STEP 11-8 — Admin AI Review Assignment / Review / Decision API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.ai.review.service import AIReviewError, AIReviewService
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

assignments_router = APIRouter(
    prefix="/api/v1/admin/ai/review-assignments",
    tags=["Admin AI Review Assignments"],
    dependencies=[Depends(require_admin)],
)

reviews_router = APIRouter(
    prefix="/api/v1/admin/ai/reviews",
    tags=["Admin AI Reviews"],
    dependencies=[Depends(require_admin)],
)

decisions_router = APIRouter(
    prefix="/api/v1/admin/ai/review-decisions",
    tags=["Admin AI Review Decisions"],
    dependencies=[Depends(require_admin)],
)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class CreateAssignmentBody(BaseModel):
    analysis_source_type: str
    source_analysis_id: int
    assigned_reviewer_id: str | None = None
    priority: str = "NORMAL"
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str | None = None


class AssignBody(BaseModel):
    reviewer_id: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=500)
    expected_version: int | None = None


class ReviewScoresBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    correctness_score: float
    relevance_score: float
    completeness_score: float
    citation_score: float
    safety_score: float
    clarity_score: float
    decision: str
    calibration_score: float | None = None
    data_quality_score: float | None = None
    reviewer_confidence: float | None = None
    findings_summary: str | None = None
    correction_summary: str | None = None
    revision_request: str | None = None
    findings: list[dict[str, Any]] | None = None


class AmendReviewBody(BaseModel):
    amendment_reason: str = Field(min_length=1, max_length=500)
    correctness_score: float
    relevance_score: float
    completeness_score: float
    citation_score: float
    safety_score: float
    clarity_score: float
    decision: str
    findings: list[dict[str, Any]] | None = None


class OverrideDecisionBody(BaseModel):
    decision: str
    reason: str = Field(min_length=1, max_length=500)
    expected_version: int | None = None


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


def _raise(exc: AIReviewError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    if exc.code in {"FORBIDDEN", "CRITICAL_SAFETY"}:
        code = status.HTTP_403_FORBIDDEN
    if exc.code == "VERSION_CONFLICT":
        code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


# --- Review Assignments ---


@assignments_router.post("")
def create_assignment(
    body: CreateAssignmentBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIReviewService(session).create_assignment(
            actor=actor,
            reason=body.reason,
            analysis_source_type=body.analysis_source_type,
            source_analysis_id=body.source_analysis_id,
            assigned_reviewer_id=body.assigned_reviewer_id,
            priority=body.priority,
            idempotency_key=body.idempotency_key,
        )
    except AIReviewError as exc:
        _raise(exc)
    if not result.get("idempotent_replay"):
        _audit(
            session,
            event_type="AI_REVIEW_ASSIGNMENT_CREATED",
            actor=actor,
            detail={
                "assignment_id": result["assignment"]["id"],
                "analysis_source_type": body.analysis_source_type,
                "source_analysis_id": body.source_analysis_id,
                "assigned_reviewer_id": body.assigned_reviewer_id,
            },
        )
    return result


@assignments_router.get("")
def list_assignments(
    assignment_status: str | None = Query(None, alias="status"),
    limit: int = 50,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIReviewService(session).list_assignments(
        status=assignment_status, limit=limit
    )
    return {"count": len(items), "items": items}


@assignments_router.get("/{assignment_id}")
def get_assignment(
    assignment_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return {"assignment": AIReviewService(session).get_assignment(assignment_id)}
    except AIReviewError as exc:
        _raise(exc)
        raise  # pragma: no cover


@assignments_router.post("/{assignment_id}/assign")
def assign_reviewer(
    assignment_id: int,
    body: AssignBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIReviewService(session).assign(
            assignment_id,
            actor=actor,
            reviewer_id=body.reviewer_id,
            reason=body.reason,
            expected_version=body.expected_version,
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_REVIEW_ASSIGNED",
        actor=actor,
        detail={
            "assignment_id": assignment_id,
            "reviewer_id": body.reviewer_id,
        },
    )
    return result


@assignments_router.post("/{assignment_id}/reassign")
def reassign_reviewer(
    assignment_id: int,
    body: AssignBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIReviewService(session).reassign(
            assignment_id,
            actor=actor,
            reviewer_id=body.reviewer_id,
            reason=body.reason,
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_REVIEW_REASSIGNED",
        actor=actor,
        detail={
            "assignment_id": assignment_id,
            "reviewer_id": body.reviewer_id,
        },
    )
    return result


@assignments_router.post("/{assignment_id}/cancel")
def cancel_assignment(
    assignment_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIReviewService(session).cancel_assignment(
            assignment_id, actor=actor, reason=body.reason
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_REVIEW_ASSIGNMENT_CANCELLED",
        actor=actor,
        detail={"assignment_id": assignment_id, "reason": body.reason},
    )
    return result


@assignments_router.post("/{assignment_id}/reviews")
def create_review_draft(
    assignment_id: int,
    body: ReviewScoresBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    reviewer_id = admin_actor_label(user)
    try:
        result = AIReviewService(session).create_review_draft(
            assignment_id,
            reviewer_id=reviewer_id,
            reason=body.reason,
            correctness_score=body.correctness_score,
            relevance_score=body.relevance_score,
            completeness_score=body.completeness_score,
            citation_score=body.citation_score,
            safety_score=body.safety_score,
            clarity_score=body.clarity_score,
            decision=body.decision,
            calibration_score=body.calibration_score,
            data_quality_score=body.data_quality_score,
            reviewer_confidence=body.reviewer_confidence,
            findings_summary=body.findings_summary,
            correction_summary=body.correction_summary,
            revision_request=body.revision_request,
            findings=body.findings,
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_REVIEW_DRAFT_SAVED",
        actor=reviewer_id,
        detail={
            "assignment_id": assignment_id,
            "review_id": result["review"]["id"],
            "decision": body.decision,
        },
    )
    return result


@assignments_router.get("/{assignment_id}/reviews")
def list_assignment_reviews(
    assignment_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIReviewService(session).list_reviews(assignment_id)
    return {"count": len(items), "items": items}


# --- Reviews ---


@reviews_router.get("/dashboard")
def reviews_dashboard(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AIReviewService(session).dashboard_summary()


@reviews_router.get("/{review_id}")
def get_review(
    review_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return {"review": AIReviewService(session).get_review(review_id)}
    except AIReviewError as exc:
        _raise(exc)
        raise  # pragma: no cover


@reviews_router.post("/{review_id}/submit")
def submit_review(
    review_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    reviewer_id = admin_actor_label(user)
    try:
        result = AIReviewService(session).submit_review(
            review_id, reviewer_id=reviewer_id, reason=body.reason
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_REVIEW_SUBMITTED",
        actor=reviewer_id,
        detail={
            "review_id": review_id,
            "decision": result["review"].get("decision"),
        },
    )
    return result


@reviews_router.post("/{review_id}/amend")
def amend_review(
    review_id: int,
    body: AmendReviewBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    reviewer_id = admin_actor_label(user)
    try:
        result = AIReviewService(session).amend_review(
            review_id,
            reviewer_id=reviewer_id,
            amendment_reason=body.amendment_reason,
            correctness_score=body.correctness_score,
            relevance_score=body.relevance_score,
            completeness_score=body.completeness_score,
            citation_score=body.citation_score,
            safety_score=body.safety_score,
            clarity_score=body.clarity_score,
            decision=body.decision,
            findings=body.findings,
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_REVIEW_AMENDED",
        actor=reviewer_id,
        detail={
            "review_id": review_id,
            "new_review_id": result["review"]["id"],
            "decision": body.decision,
        },
    )
    return result


@reviews_router.post("/{review_id}/withdraw")
def withdraw_review(
    review_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    reviewer_id = admin_actor_label(user)
    try:
        result = AIReviewService(session).withdraw_review(
            review_id, reviewer_id=reviewer_id, reason=body.reason
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_REVIEW_WITHDRAWN",
        actor=reviewer_id,
        detail={"review_id": review_id, "reason": body.reason},
    )
    return result


# --- Review Decisions ---


@decisions_router.get("/{source_type}/{source_id}")
def get_decision(
    source_type: str,
    source_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return {"decision": AIReviewService(session).get_decision(source_type, source_id)}
    except AIReviewError as exc:
        _raise(exc)
        raise  # pragma: no cover


@decisions_router.post("/{source_type}/{source_id}/recalculate")
def recalculate_decision(
    source_type: str,
    source_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIReviewService(session).recalculate_decision(
            source_type, source_id, actor=actor
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_REVIEW_DECISION_RECALCULATED",
        actor=actor,
        detail={
            "source_type": source_type,
            "source_id": source_id,
            "decision": result.get("decision"),
            "reason": body.reason,
        },
    )
    return {"decision": result}


@decisions_router.post("/{source_type}/{source_id}/override")
def override_decision(
    source_type: str,
    source_id: int,
    body: OverrideDecisionBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIReviewService(session).override_decision(
            source_type,
            source_id,
            actor=actor,
            decision=body.decision,
            reason=body.reason,
            expected_version=body.expected_version,
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_REVIEW_DECISION_OVERRIDDEN",
        actor=actor,
        detail={
            "source_type": source_type,
            "source_id": source_id,
            "decision": body.decision,
            "reason": body.reason,
        },
    )
    return {"decision": result}
