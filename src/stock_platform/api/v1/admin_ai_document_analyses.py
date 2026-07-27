"""STEP 11-6 — Admin AI Document Analysis API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.document_analysis.eligibility import (
    AIDocumentEligibilityService,
)
from stock_platform.ai.document_analysis.service import (
    AIAnalysisBatchService,
    AIDocumentAnalysisError,
    AIDocumentAnalysisService,
)
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/ai/document-analyses",
    tags=["Admin AI Document Analyses"],
    dependencies=[Depends(require_admin)],
)


class CreateBody(BaseModel):
    document_type: str
    source_document_id: int
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)
    execution_mode: str = "MOCK"
    provider_configuration_id: int | None = None
    provider_code: str | None = "mock"
    model: str | None = None
    prompt_version_id: int | None = None
    max_tokens: int = 512
    timeout_sec: float = 30.0
    fallback_enabled: bool = False
    force_new_version: bool = False
    has_internal_notes: bool = False
    correlation_id: str | None = None


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    confirm: bool = False


class BatchBody(BaseModel):
    document_type: str
    source_document_ids: list[int]
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)
    execution_mode: str = "MOCK"
    provider_code: str = "mock"
    model: str | None = None
    prompt_version_id: int | None = None
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


def _raise(exc: AIDocumentAnalysisError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    if exc.code in {"CONFIRM_REQUIRED", "DATA_POLICY_BLOCKED"}:
        code = status.HTTP_403_FORBIDDEN
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.get("")
def list_analyses(
    document_type: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIDocumentAnalysisService(session).list_analyses(
        document_type=document_type, limit=limit
    )
    return {"count": len(items), "items": items}


@router.get("/dashboard")
def dashboard(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AIDocumentAnalysisService(session).dashboard_summary()


@router.post("/eligibility")
def eligibility(
    body: CreateBody,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    result = AIDocumentEligibilityService(session).evaluate(
        document_type=body.document_type,
        source_document_id=body.source_document_id,
        execution_mode=body.execution_mode,
        provider_code=body.provider_code or "mock",
        prompt_version_id=body.prompt_version_id,
        has_internal_notes=body.has_internal_notes,
    )
    # 원문 전체는 응답에서 제거
    result = dict(result)
    result.pop("normalized", None)
    return result


@router.post("")
def create_analysis(
    body: CreateBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIDocumentAnalysisService(session).create(
            actor=actor,
            reason=body.reason,
            document_type=body.document_type,
            source_document_id=body.source_document_id,
            execution_mode=body.execution_mode,
            provider_code=body.provider_code,
            model=body.model,
            prompt_version_id=body.prompt_version_id,
            max_tokens=body.max_tokens,
            timeout_sec=body.timeout_sec,
            fallback_enabled=body.fallback_enabled,
            idempotency_key=body.idempotency_key,
            force_new_version=body.force_new_version,
            correlation_id=body.correlation_id,
            has_internal_notes=body.has_internal_notes,
        )
    except AIDocumentAnalysisError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_DOCUMENT_ANALYSIS_CREATED",
        actor=actor,
        detail={
            "analysis_id": result["analysis"]["id"],
            "document_type": body.document_type,
            "source_document_id": body.source_document_id,
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
        result = AIAnalysisBatchService(session).create_batch(
            actor=actor,
            reason=body.reason,
            document_type=body.document_type,
            source_document_ids=body.source_document_ids,
            execution_mode=body.execution_mode,
            provider_code=body.provider_code,
            model=body.model,
            prompt_version_id=body.prompt_version_id,
            confirm=body.confirm,
            idempotency_key=body.idempotency_key,
            estimated_max_tokens=body.estimated_max_tokens,
            estimated_max_cost=body.estimated_max_cost,
        )
    except AIDocumentAnalysisError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_DOCUMENT_ANALYSIS_BATCH_CREATED",
        actor=actor,
        detail={
            "created_count": result["created_count"],
            "document_type": body.document_type,
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
        return AIDocumentAnalysisService(session).compare(
            body.left_id, body.right_id
        )
    except AIDocumentAnalysisError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{analysis_id}")
def get_analysis(
    analysis_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return {
            "analysis": AIDocumentAnalysisService(session).get(analysis_id)
        }
    except AIDocumentAnalysisError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{analysis_id}/history")
def get_history(
    analysis_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIDocumentAnalysisService(session).history(analysis_id)
    return {"count": len(items), "items": items}


@router.post("/{analysis_id}/dry-run")
def dry_run(
    analysis_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIDocumentAnalysisService(session).dry_run(
            analysis_id, actor=actor
        )
    except AIDocumentAnalysisError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_DOCUMENT_ANALYSIS_DRY_RUN_COMPLETED",
        actor=actor,
        detail={"analysis_id": analysis_id, "reason": body.reason},
    )
    return result


@router.post("/{analysis_id}/execute")
async def execute(
    analysis_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = await AIDocumentAnalysisService(session).execute(
            analysis_id, actor=actor, confirm=body.confirm
        )
    except AIDocumentAnalysisError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_DOCUMENT_ANALYSIS_COMPLETED",
        actor=actor,
        detail={
            "analysis_id": analysis_id,
            "ok": result.get("ok"),
            "external_ai_called": result.get("external_ai_called"),
            "reason": body.reason,
        },
    )
    return result


@router.post("/{analysis_id}/cancel")
def cancel(
    analysis_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIDocumentAnalysisService(session).cancel(
            analysis_id, actor=actor, reason=body.reason
        )
    except AIDocumentAnalysisError as exc:
        _raise(exc)
    return result


@router.post("/{analysis_id}/reanalyze")
def reanalyze(
    analysis_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIDocumentAnalysisService(session).reanalyze(
            analysis_id,
            actor=actor,
            reason=body.reason,
            idempotency_key=f"re-{analysis_id}-{body.reason[:20]}",
            force_new_version=True,
        )
    except AIDocumentAnalysisError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_DOCUMENT_ANALYSIS_REANALYSIS_CREATED",
        actor=actor,
        detail={"previous_id": analysis_id, "new_id": result["analysis"]["id"]},
    )
    return result
