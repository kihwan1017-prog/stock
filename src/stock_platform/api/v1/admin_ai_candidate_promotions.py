"""STEP 11-12 — Admin AI Candidate Promotion Gateway API.

Create/Validate/Dry-run/Approve → Candidate INSERT 0.
Commit(confirm=true) 만 CandidateRun/Result 생성.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_promotion.batch_service import (
    AICandidatePromotionBatchService,
)
from stock_platform.ai.candidate_promotion.service import (
    AICandidatePromotionError,
    AICandidatePromotionService,
)
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/ai/candidate-promotions",
    tags=["Admin AI Candidate Promotions"],
    dependencies=[Depends(require_admin)],
)


class CreateBody(BaseModel):
    queue_id: int
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)
    allow_existing_candidate_override: bool = False
    override_reason: str | None = None
    correlation_id: str | None = None


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    allow_existing_candidate_override: bool = False
    override_reason: str | None = None
    correlation_id: str | None = None


class ApproveBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    manager_override: bool = False
    override_reason: str | None = None
    warning_acknowledgements: dict[str, Any] | None = None
    correlation_id: str | None = None


class CommitBody(BaseModel):
    confirm: bool = False
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)
    correlation_id: str | None = None


class BatchBody(BaseModel):
    queue_ids: list[int] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)
    confirm: bool = False
    allow_existing_candidate_override: bool = False
    override_reason: str | None = None


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


def _raise(exc: AICandidatePromotionError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    if exc.code in {
        "CONFIRM_REQUIRED",
        "NOT_ELIGIBLE",
        "SELF_APPROVAL_BLOCKED",
        "CRITICAL_FINDINGS_BLOCK",
        "PROMOTION_RUN_TYPE_FORBIDDEN",
    }:
        code = status.HTTP_403_FORBIDDEN
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.get("")
def list_promotions(
    status_filter: str | None = None,
    exchange_code: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AICandidatePromotionService(session).list(
        status=status_filter,
        exchange_code=exchange_code,
        symbol=symbol,
        limit=min(limit, 200),
        offset=offset,
    )


@router.get("/dashboard")
def promotion_dashboard(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    summary = AICandidatePromotionService(session).dashboard_summary()
    summary["external_calls_on_read"] = 0
    return summary


@router.post("")
def create_promotion(
    body: CreateBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).create(
            queue_id=body.queue_id,
            actor=actor,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
            allow_existing_candidate_override=body.allow_existing_candidate_override,
            override_reason=body.override_reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_PROMOTION_CREATED",
        actor=actor,
        detail={"queue_id": body.queue_id, "reason": body.reason},
    )
    return result


@router.post("/batches")
def create_batch(
    body: BatchBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CONFIRM_REQUIRED", "message": "batch confirm=true required"},
        )
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionBatchService(session).create_batch(
            actor=actor,
            reason=body.reason,
            queue_ids=body.queue_ids,
            idempotency_key=body.idempotency_key,
            allow_existing_candidate_override=body.allow_existing_candidate_override,
            override_reason=body.override_reason,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/compare")
def compare_promotions(
    body: CompareBody,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AICandidatePromotionService(session).compare(body.left_id, body.right_id)
    except AICandidatePromotionError as exc:
        _raise(exc)
    return {}


@router.get("/{promotion_id}")
def get_promotion(
    promotion_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AICandidatePromotionService(session).get(promotion_id)
    except AICandidatePromotionError as exc:
        _raise(exc)
    return {}


@router.get("/{promotion_id}/validations")
def get_validations(
    promotion_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AICandidatePromotionService(session).get_validations(promotion_id)


@router.get("/{promotion_id}/dry-runs")
def get_dry_runs(
    promotion_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AICandidatePromotionService(session).get_dry_runs(promotion_id)


@router.get("/{promotion_id}/approvals")
def get_approvals(
    promotion_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AICandidatePromotionService(session).get_approvals(promotion_id)


@router.get("/{promotion_id}/history")
def get_history(
    promotion_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AICandidatePromotionService(session).get_history(promotion_id)


@router.get("/{promotion_id}/candidate")
def get_candidate(
    promotion_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AICandidatePromotionService(session).get_candidate(promotion_id)


@router.post("/{promotion_id}/validate")
def validate_promotion(
    promotion_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).validate(
            promotion_id,
            actor=actor,
            reason=body.reason,
            allow_existing_candidate_override=body.allow_existing_candidate_override,
            override_reason=body.override_reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/dry-run")
def dry_run_promotion(
    promotion_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).dry_run(
            promotion_id,
            actor=actor,
            reason=body.reason,
            allow_existing_candidate_override=body.allow_existing_candidate_override,
            override_reason=body.override_reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/submit-first-approval")
def submit_first(
    promotion_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).submit_first_approval(
            promotion_id,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/approve-first")
def approve_first(
    promotion_id: int,
    body: ApproveBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).approve_first(
            promotion_id,
            actor=actor,
            reason=body.reason,
            manager_override=body.manager_override,
            override_reason=body.override_reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/reject-first")
def reject_first(
    promotion_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).reject_first(
            promotion_id,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/submit-final-approval")
def submit_final(
    promotion_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).submit_final_approval(
            promotion_id,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/approve-final")
def approve_final(
    promotion_id: int,
    body: ApproveBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).approve_final(
            promotion_id,
            actor=actor,
            reason=body.reason,
            warning_acknowledgements=body.warning_acknowledgements,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/reject-final")
def reject_final(
    promotion_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).reject_final(
            promotion_id,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/commit")
def commit_promotion(
    promotion_id: int,
    body: CommitBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """유일한 Candidate INSERT 경로 — confirm=true 필수."""
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).commit(
            promotion_id,
            confirm=body.confirm,
            idempotency_key=body.idempotency_key,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_PROMOTION_COMPLETED",
        actor=actor,
        detail={
            "promotion_request_id": promotion_id,
            "candidate_run_id": (result.get("promotion") or {}).get("candidate_run_id"),
            "candidate_result_id": (result.get("promotion") or {}).get(
                "candidate_result_id"
            ),
        },
    )
    return result


@router.post("/{promotion_id}/cancel")
def cancel_promotion(
    promotion_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).cancel(
            promotion_id, actor=actor, reason=body.reason, correlation_id=body.correlation_id
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/expire")
def expire_promotion(
    promotion_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).expire(
            promotion_id, actor=actor, reason=body.reason, correlation_id=body.correlation_id
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/revalidate")
def revalidate_promotion(
    promotion_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).revalidate(
            promotion_id,
            actor=actor,
            reason=body.reason,
            allow_existing_candidate_override=body.allow_existing_candidate_override,
            override_reason=body.override_reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/recreate-dry-run")
def recreate_dry_run(
    promotion_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).recreate_dry_run(
            promotion_id,
            actor=actor,
            reason=body.reason,
            allow_existing_candidate_override=body.allow_existing_candidate_override,
            override_reason=body.override_reason,
            correlation_id=body.correlation_id,
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result


@router.post("/{promotion_id}/rollback")
def rollback_promotion(
    promotion_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidatePromotionService(session).rollback(
            promotion_id, actor=actor, reason=body.reason, correlation_id=body.correlation_id
        )
        session.commit()
    except AICandidatePromotionError as exc:
        session.rollback()
        _raise(exc)
    return result
