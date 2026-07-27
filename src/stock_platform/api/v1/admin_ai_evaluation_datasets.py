"""STEP 11-8 — Admin AI Evaluation Dataset API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.ai.review.dataset_service import AIEvaluationDatasetService
from stock_platform.ai.review.service import AIReviewError
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/ai/evaluation-datasets",
    tags=["Admin AI Evaluation Datasets"],
    dependencies=[Depends(require_admin)],
)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class CreateDatasetBody(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    task_type: str
    description: str = ""
    reason: str = Field(min_length=1, max_length=500)


class UpdateDatasetBody(BaseModel):
    name: str | None = None
    description: str | None = None
    reason: str = Field(min_length=1, max_length=500)


class AddItemBody(BaseModel):
    input_reference_hash: str | None = None
    source_analysis_id: int | None = None
    source_document_key: str | None = None
    snapshot_key: str | None = None
    expected_result: dict[str, Any] | None = None
    expected_schema_version: str | None = None
    grading_rubric: dict[str, Any] | None = None
    data_classification: str = "PUBLIC"
    reason: str = Field(min_length=1, max_length=500)


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
    if exc.code in {"ACTIVE_IMMUTABLE", "DATA_POLICY_BLOCKED"}:
        code = status.HTTP_403_FORBIDDEN
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.post("")
def create_dataset(
    body: CreateDatasetBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIEvaluationDatasetService(session).create(
            actor=actor,
            code=body.code,
            name=body.name,
            task_type=body.task_type,
            description=body.description,
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_EVALUATION_DATASET_CREATED",
        actor=actor,
        detail={
            "dataset_id": result["dataset"]["id"],
            "code": body.code,
            "task_type": body.task_type,
            "reason": body.reason,
        },
    )
    return result


@router.get("")
def list_datasets(
    limit: int = 50,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIEvaluationDatasetService(session).list_datasets(limit=limit)
    return {"count": len(items), "items": items}


@router.get("/{dataset_id}")
def get_dataset(
    dataset_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return {"dataset": AIEvaluationDatasetService(session).get(dataset_id)}
    except AIReviewError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.patch("/{dataset_id}")
def update_dataset(
    dataset_id: int,
    body: UpdateDatasetBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIEvaluationDatasetService(session).update_meta(
            dataset_id,
            actor=actor,
            name=body.name,
            description=body.description,
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_EVALUATION_DATASET_UPDATED",
        actor=actor,
        detail={"dataset_id": dataset_id, "reason": body.reason},
    )
    return result


@router.post("/{dataset_id}/items")
def add_dataset_item(
    dataset_id: int,
    body: AddItemBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIEvaluationDatasetService(session).add_item(
            dataset_id,
            actor=actor,
            input_reference_hash=body.input_reference_hash,
            source_analysis_id=body.source_analysis_id,
            source_document_key=body.source_document_key,
            snapshot_key=body.snapshot_key,
            expected_result=body.expected_result,
            expected_schema_version=body.expected_schema_version,
            grading_rubric=body.grading_rubric,
            data_classification=body.data_classification,
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_EVALUATION_DATASET_ITEM_ADDED",
        actor=actor,
        detail={
            "dataset_id": dataset_id,
            "item_id": result["item"]["id"],
            "data_classification": body.data_classification,
            "reason": body.reason,
        },
    )
    return result


@router.post("/{dataset_id}/validate")
def validate_dataset(
    dataset_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIEvaluationDatasetService(session).validate(
            dataset_id, actor=actor
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_EVALUATION_DATASET_VALIDATED",
        actor=actor,
        detail={"dataset_id": dataset_id, "reason": body.reason},
    )
    return result


@router.post("/{dataset_id}/activate")
def activate_dataset(
    dataset_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIEvaluationDatasetService(session).activate(
            dataset_id, actor=actor
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_EVALUATION_DATASET_ACTIVATED",
        actor=actor,
        detail={"dataset_id": dataset_id, "reason": body.reason},
    )
    return result


@router.post("/{dataset_id}/archive")
def archive_dataset(
    dataset_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIEvaluationDatasetService(session).archive(
            dataset_id, actor=actor
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_EVALUATION_DATASET_ARCHIVED",
        actor=actor,
        detail={"dataset_id": dataset_id, "reason": body.reason},
    )
    return result


@router.get("/{dataset_id}/items")
def list_dataset_items(
    dataset_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIEvaluationDatasetService(session).list_items(dataset_id)
    return {"count": len(items), "items": items}
