"""STEP 11-13 — Admin AI Candidate Lifecycle API.

Promotion으로 등록된 CandidateResult(result_id)의 참조·검증·만료·철회 관리.
AI 호출·매매·주문·전략 WRITE 없음 — soft status 전이만.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.entities import AICandidateRevocationEntity
from stock_platform.ai.candidate_lifecycle.service import (
    AICandidateLifecycleError,
    AICandidateLifecycleService,
)
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/ai/candidate-lifecycle",
    tags=["Admin AI Candidate Lifecycle"],
    dependencies=[Depends(require_admin)],
)

candidates_router = APIRouter(
    prefix="/api/v1/admin/ai/candidates",
    tags=["Admin AI Candidate Lifecycle"],
    dependencies=[Depends(require_admin)],
)

dashboard_router = APIRouter(
    prefix="/api/v1/admin/dashboard",
    tags=["Admin AI Candidate Lifecycle"],
    dependencies=[Depends(require_admin)],
)


class MutationBody(BaseModel):
    expected_version: int
    reason: str = Field(min_length=1, max_length=500)
    correlation_id: str | None = None
    idempotency_key: str | None = None
    revalidation_key: str | None = None
    revocation_key: str | None = None


class SupersedeBody(BaseModel):
    replacement_candidate_id: int
    expected_version: int
    reason: str = Field(min_length=1, max_length=500)
    correlation_id: str | None = None


def _audit(
    session: Session,
    *,
    event_type: str,
    actor: str,
    detail: dict[str, Any],
) -> None:
    try:
        AuditLogService(session).record(
            event_type=event_type,
            actor=actor,
            detail=sanitize_for_log(detail),
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _raise(exc: AICandidateLifecycleError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    elif exc.code == "VERSION_CONFLICT":
        code = status.HTTP_409_CONFLICT
    elif exc.code in {
        "REVOCATION_BLOCKED",
        "SUPERSESSION_BLOCKED",
        "NOT_PROMOTED",
        "PROVENANCE_MISSING",
    }:
        code = status.HTTP_403_FORBIDDEN
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


def _lifecycle_dashboard(session: Session) -> dict[str, Any]:
    summary = AICandidateLifecycleService(session).dashboard_summary()
    summary["external_calls_on_read"] = 0
    return summary


@router.get("")
def list_lifecycles(
    lifecycle_status: str | None = None,
    health_status: str | None = None,
    revalidation_required: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AICandidateLifecycleService(session).list_lifecycles(
        lifecycle_status=lifecycle_status,
        health_status=health_status,
        revalidation_required=revalidation_required,
        limit=min(limit, 200),
        offset=offset,
    )


@router.get("/dashboard")
def lifecycle_dashboard(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return _lifecycle_dashboard(session)


@dashboard_router.get("/ai-candidate-lifecycle-summary")
def lifecycle_dashboard_summary(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return _lifecycle_dashboard(session)


@candidates_router.get("/{candidate_id}/lifecycle")
def get_lifecycle(
    candidate_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AICandidateLifecycleService(session).get(candidate_id)
    except AICandidateLifecycleError as exc:
        _raise(exc)
    return {}


@candidates_router.get("/{candidate_id}/provenance")
def get_provenance(
    candidate_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AICandidateLifecycleService(session).get_provenance(candidate_id)
    except AICandidateLifecycleError as exc:
        _raise(exc)
    return {}


@candidates_router.get("/{candidate_id}/history")
def get_history(
    candidate_id: int,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AICandidateLifecycleService(session).get_history(
            candidate_id, limit=min(limit, 200), offset=offset
        )
    except AICandidateLifecycleError as exc:
        _raise(exc)
    return {}


@candidates_router.get("/{candidate_id}/revalidations")
def get_revalidations(
    candidate_id: int,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AICandidateLifecycleService(session).get_revalidations(
            candidate_id, limit=min(limit, 200), offset=offset
        )
    except AICandidateLifecycleError as exc:
        _raise(exc)
    return {}


@candidates_router.get("/{candidate_id}/revocations")
def get_revocations(
    candidate_id: int,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AICandidateLifecycleService(session).get_revocations(
            candidate_id, limit=min(limit, 200), offset=offset
        )
    except AICandidateLifecycleError as exc:
        _raise(exc)
    return {}


@candidates_router.post("/{candidate_id}/activate-review")
def activate_review(
    candidate_id: int,
    body: MutationBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateLifecycleService(session).activate_review(
            candidate_id,
            expected_version=body.expected_version,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidateLifecycleError as exc:
        session.rollback()
        _raise(exc)
    _audit(
        session,
        event_type="CANDIDATE_LIFECYCLE_STATUS_CHANGED",
        actor=actor,
        detail={
            "candidate_id": candidate_id,
            "action": "ACTIVE_REVIEW",
            "reason": body.reason,
        },
    )
    return result


@candidates_router.post("/{candidate_id}/validate")
def validate_lifecycle(
    candidate_id: int,
    body: MutationBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateLifecycleService(session).validate(
            candidate_id,
            expected_version=body.expected_version,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidateLifecycleError as exc:
        session.rollback()
        _raise(exc)
    _audit(
        session,
        event_type="CANDIDATE_LIFECYCLE_VALIDATED",
        actor=actor,
        detail={"candidate_id": candidate_id, "reason": body.reason},
    )
    return result


@candidates_router.post("/{candidate_id}/revalidate")
def revalidate_lifecycle(
    candidate_id: int,
    body: MutationBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateLifecycleService(session).revalidate(
            candidate_id,
            expected_version=body.expected_version,
            actor=actor,
            reason=body.reason,
            revalidation_key=body.revalidation_key,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidateLifecycleError as exc:
        session.rollback()
        _raise(exc)
    _audit(
        session,
        event_type="CANDIDATE_LIFECYCLE_REVALIDATED",
        actor=actor,
        detail={"candidate_id": candidate_id, "reason": body.reason},
    )
    return result


@candidates_router.post("/{candidate_id}/expire")
def expire_lifecycle(
    candidate_id: int,
    body: MutationBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateLifecycleService(session).expire(
            candidate_id,
            expected_version=body.expected_version,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidateLifecycleError as exc:
        session.rollback()
        _raise(exc)
    _audit(
        session,
        event_type="CANDIDATE_EXPIRED",
        actor=actor,
        detail={"candidate_id": candidate_id, "reason": body.reason},
    )
    return result


@candidates_router.post("/{candidate_id}/archive")
def archive_lifecycle(
    candidate_id: int,
    body: MutationBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateLifecycleService(session).archive(
            candidate_id,
            expected_version=body.expected_version,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidateLifecycleError as exc:
        session.rollback()
        _raise(exc)
    _audit(
        session,
        event_type="CANDIDATE_ARCHIVED",
        actor=actor,
        detail={"candidate_id": candidate_id, "reason": body.reason},
    )
    return result


@candidates_router.post("/{candidate_id}/supersede")
def supersede_lifecycle(
    candidate_id: int,
    body: SupersedeBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateLifecycleService(session).supersede(
            candidate_id,
            body.replacement_candidate_id,
            expected_version=body.expected_version,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidateLifecycleError as exc:
        session.rollback()
        _raise(exc)
    _audit(
        session,
        event_type="CANDIDATE_SUPERSEDED",
        actor=actor,
        detail={
            "previous_candidate_id": candidate_id,
            "replacement_candidate_id": body.replacement_candidate_id,
            "reason": body.reason,
        },
    )
    return result


@candidates_router.post("/{candidate_id}/revocations")
def request_revocation(
    candidate_id: int,
    body: MutationBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateLifecycleService(session).request_revocation(
            candidate_id,
            expected_version=body.expected_version,
            actor=actor,
            reason=body.reason,
            revocation_key=body.revocation_key,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidateLifecycleError as exc:
        session.rollback()
        _raise(exc)
    _audit(
        session,
        event_type="CANDIDATE_REVOCATION_REQUESTED",
        actor=actor,
        detail={"candidate_id": candidate_id, "reason": body.reason},
    )
    return result


def _revocation_key_for_id(
    session: Session,
    candidate_id: int,
    revocation_id: int,
) -> str:
    rev = session.get(AICandidateRevocationEntity, revocation_id)
    if rev is None or rev.candidate_id != candidate_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "revocation missing"},
        )
    return rev.revocation_key


@candidates_router.post("/{candidate_id}/revocations/{revocation_id}/approve")
def approve_revocation(
    candidate_id: int,
    revocation_id: int,
    body: MutationBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    revocation_key = _revocation_key_for_id(session, candidate_id, revocation_id)
    try:
        result = AICandidateLifecycleService(session).approve_revocation(
            candidate_id,
            revocation_key=revocation_key,
            expected_version=body.expected_version,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidateLifecycleError as exc:
        session.rollback()
        _raise(exc)
    _audit(
        session,
        event_type="CANDIDATE_REVOKED",
        actor=actor,
        detail={
            "candidate_id": candidate_id,
            "revocation_id": revocation_id,
            "reason": body.reason,
        },
    )
    return result


@candidates_router.post("/{candidate_id}/revocations/{revocation_id}/cancel")
def cancel_revocation(
    candidate_id: int,
    revocation_id: int,
    body: MutationBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    revocation_key = _revocation_key_for_id(session, candidate_id, revocation_id)
    try:
        result = AICandidateLifecycleService(session).cancel_revocation(
            candidate_id,
            revocation_key=revocation_key,
            expected_version=body.expected_version,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidateLifecycleError as exc:
        session.rollback()
        _raise(exc)
    _audit(
        session,
        event_type="CANDIDATE_REVOCATION_CANCELLED",
        actor=actor,
        detail={
            "candidate_id": candidate_id,
            "revocation_id": revocation_id,
            "reason": body.reason,
        },
    )
    return result
