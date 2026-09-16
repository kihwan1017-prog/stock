"""STEP 11-9 — Admin AI Candidate Assessment API (참고용 초안, 매매 후보 아님)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_assessment.batch_service import (
    AICandidateAssessmentBatchService,
)
from stock_platform.ai.candidate_assessment.service import (
    AICandidateAssessmentError,
    AICandidateAssessmentService,
)
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/ai/candidate-assessments",
    tags=["Admin AI Candidate Assessments"],
    dependencies=[Depends(require_admin)],
)


class CreateBody(BaseModel):
    market_type: str
    exchange_code: str
    symbol: str
    instrument_id: int | None = None
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)
    execution_mode: str = "MOCK"
    provider_code: str | None = "mock"
    model: str | None = None
    prompt_version_id: int | None = None
    max_tokens: int = 768
    timeout_sec: float = 45.0
    fallback_enabled: bool = False
    include_news: bool = True
    include_disclosure: bool = True
    include_chart: bool = True
    include_market: bool = True
    require_reviewed_evidence: bool = False
    force_new_version: bool = False
    correlation_id: str | None = None


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    confirm: bool = False


class ReassessBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)


class RequestReviewBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    assigned_reviewer_id: str | None = None


class BatchBody(BaseModel):
    market_type: str
    exchange_code: str
    instruments: list[dict[str, Any]]
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)
    execution_mode: str = "MOCK"
    provider_code: str = "mock"
    model: str | None = None
    prompt_version_id: int | None = None
    include_news: bool = True
    include_disclosure: bool = True
    include_chart: bool = True
    include_market: bool = True
    require_reviewed_evidence: bool = False
    confirm: bool = False
    estimated_max_tokens: int | None = None
    estimated_max_cost: float | None = None


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


def _raise(exc: AICandidateAssessmentError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    if exc.code in {
        "CONFIRM_REQUIRED",
        "DATA_QUALITY_INVALID",
        "NOT_ELIGIBLE",
    }:
        code = status.HTTP_403_FORBIDDEN
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.get("")
def list_assessments(
    market_type: str | None = None,
    assessment_type: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AICandidateAssessmentService(session).list(
        market_type=market_type,
        assessment_type=assessment_type,
        limit=limit,
    )
    return {"count": len(items), "items": items}


@router.get("/dashboard")
def dashboard(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AICandidateAssessmentService(session).dashboard_summary()


@router.post("")
def create_assessment(
    body: CreateBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateAssessmentService(session).create(
            actor=actor,
            reason=body.reason,
            market_type=body.market_type,
            exchange_code=body.exchange_code,
            symbol=body.symbol,
            instrument_id=body.instrument_id,
            execution_mode=body.execution_mode,
            provider_code=body.provider_code,
            model=body.model,
            prompt_version_id=body.prompt_version_id,
            max_tokens=body.max_tokens,
            timeout_sec=body.timeout_sec,
            fallback_enabled=body.fallback_enabled,
            include_news=body.include_news,
            include_disclosure=body.include_disclosure,
            include_chart=body.include_chart,
            include_market=body.include_market,
            require_reviewed_evidence=body.require_reviewed_evidence,
            idempotency_key=body.idempotency_key,
            force_new_version=body.force_new_version,
            correlation_id=body.correlation_id,
        )
    except AICandidateAssessmentError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_ASSESSMENT_CREATED",
        actor=actor,
        detail={
            "assessment_id": result["assessment"]["id"],
            "market_type": body.market_type,
            "exchange_code": body.exchange_code,
            "symbol": body.symbol,
            "mode": body.execution_mode,
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
        result = AICandidateAssessmentBatchService(session).create_batch(
            actor=actor,
            reason=body.reason,
            market_type=body.market_type,
            exchange_code=body.exchange_code,
            instruments=body.instruments,
            execution_mode=body.execution_mode,
            provider_code=body.provider_code,
            model=body.model,
            prompt_version_id=body.prompt_version_id,
            include_news=body.include_news,
            include_disclosure=body.include_disclosure,
            include_chart=body.include_chart,
            include_market=body.include_market,
            require_reviewed_evidence=body.require_reviewed_evidence,
            confirm=body.confirm,
            idempotency_key=body.idempotency_key,
            estimated_max_tokens=body.estimated_max_tokens,
            estimated_max_cost=body.estimated_max_cost,
        )
    except AICandidateAssessmentError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_BATCH_CREATED",
        actor=actor,
        detail={
            "created_count": result["created_count"],
            "market_type": body.market_type,
            "exchange_code": body.exchange_code,
            "instrument_count": len(body.instruments),
            "mode": body.execution_mode,
        },
    )
    return result


@router.post("/compare")
def compare(
    body: CompareBody,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AICandidateAssessmentService(session).compare(
            body.left_id, body.right_id
        )
    except AICandidateAssessmentError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{assessment_id}")
def get_assessment(
    assessment_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return {
            "assessment": AICandidateAssessmentService(session).get(assessment_id)
        }
    except AICandidateAssessmentError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{assessment_id}/history")
def get_history(
    assessment_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        items = AICandidateAssessmentService(session).get_history(assessment_id)
    except AICandidateAssessmentError as exc:
        _raise(exc)
    return {"count": len(items), "items": items}


@router.get("/{assessment_id}/evidence")
def get_evidence(
    assessment_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        items = AICandidateAssessmentService(session).get_evidence(assessment_id)
    except AICandidateAssessmentError as exc:
        _raise(exc)
    return {"count": len(items), "items": items}


@router.post("/{assessment_id}/dry-run")
def dry_run(
    assessment_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateAssessmentService(session).dry_run(
            assessment_id, actor=actor
        )
    except AICandidateAssessmentError as exc:
        _raise(exc)
    # prompt/response 원문은 서비스에서 제외됨
    _audit(
        session,
        event_type="AI_CANDIDATE_DRY_RUN_COMPLETED",
        actor=actor,
        detail={"assessment_id": assessment_id, "reason": body.reason},
    )
    return result


@router.post("/{assessment_id}/execute")
async def execute(
    assessment_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = await AICandidateAssessmentService(session).execute(
            assessment_id, actor=actor, confirm=body.confirm
        )
    except AICandidateAssessmentError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_COMPLETED",
        actor=actor,
        detail={
            "assessment_id": assessment_id,
            "ok": result.get("ok"),
            "external_ai_called": result.get("external_ai_called"),
            "reason": body.reason,
        },
    )
    return result


@router.post("/{assessment_id}/cancel")
def cancel(
    assessment_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateAssessmentService(session).cancel(
            assessment_id, actor=actor, reason=body.reason
        )
    except AICandidateAssessmentError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_CANCELLED",
        actor=actor,
        detail={"assessment_id": assessment_id, "reason": body.reason},
    )
    return result


@router.post("/{assessment_id}/reassess")
def reassess(
    assessment_id: int,
    body: ReassessBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateAssessmentService(session).reassess(
            assessment_id,
            actor=actor,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
        )
    except AICandidateAssessmentError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_REASSESSMENT_CREATED",
        actor=actor,
        detail={
            "previous_id": assessment_id,
            "new_id": result["assessment"]["id"],
            "reason": body.reason,
        },
    )
    return result


@router.post("/{assessment_id}/request-review")
def request_review(
    assessment_id: int,
    body: RequestReviewBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AICandidateAssessmentService(session).request_review(
            assessment_id,
            actor=actor,
            reason=body.reason,
            assigned_reviewer_id=body.assigned_reviewer_id,
        )
    except AICandidateAssessmentError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CANDIDATE_REVIEW_REQUESTED",
        actor=actor,
        detail={"assessment_id": assessment_id, "reason": body.reason},
    )
    return result
