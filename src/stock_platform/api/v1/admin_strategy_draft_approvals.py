"""STEP 12-3 — Admin Strategy Draft 최종 승인/반려/취소 API.

관리자가 검토 완료한 Strategy Draft를 최종 승인하거나 반려하고, 승인된
Draft로부터 불변의 Strategy Definition(trading.strategy_definition 재사용)을
생성한다. 승인/반려/취소는 모두 이 파일(및 서비스)을 통해서만 이뤄지며,
Backtest/Paper Trading/Runtime/Broker/Order/Scheduler WRITE, 전략 공개
게시, AI 자동 승인은 이 STEP의 범위가 아니다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.constants import REASON_MAX_LENGTH
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalError,
    StrategyDraftApprovalService,
)
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

router = APIRouter(
    tags=["Admin Strategy Draft Approvals"],
    dependencies=[Depends(require_admin)],
)


class ApproveDraftBody(BaseModel):
    reason: str = Field(min_length=1, max_length=REASON_MAX_LENGTH)
    idempotency_key: str | None = Field(default=None, max_length=64)
    correlation_id: str | None = None


class RejectDraftBody(BaseModel):
    reason: str = Field(min_length=1, max_length=REASON_MAX_LENGTH)
    idempotency_key: str | None = Field(default=None, max_length=64)
    correlation_id: str | None = None


class RevokeApprovalBody(BaseModel):
    reason: str = Field(min_length=1, max_length=REASON_MAX_LENGTH)
    correlation_id: str | None = None


def _audit(
    session: Session, *, event_type: str, actor: str, detail: dict[str, Any]
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


_NOT_FOUND_CODES = {
    "NOT_FOUND",
    "STRATEGY_REQUEST_NOT_FOUND",
    "CANDIDATE_NOT_FOUND",
}
_CONFLICT_CODES = {
    "INVALID_STATE_TRANSITION",
    "STRATEGY_REQUEST_NOT_APPROVED",
    "CANDIDATE_NOT_ACTIVE",
    "CANDIDATE_FINGERPRINT_CHANGED",
    "DRAFT_STATUS_NOT_APPROVABLE",
    "ALREADY_APPROVED",
    "DUPLICATE_DECISION",
    "GENERATION_NOT_SUCCEEDED",
    "DRAFT_RUN_MISMATCH",
    "NO_SUCCESSFUL_ATTEMPT",
    "STRUCTURED_VALIDATION_FAILED",
}


def _raise(exc: StrategyDraftApprovalError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code in _NOT_FOUND_CODES:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in _CONFLICT_CODES:
        code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


def _duplicate_or_invalidation_event(exc: StrategyDraftApprovalError) -> str:
    if exc.code == "ALREADY_APPROVED":
        return "STRATEGY_DRAFT_APPROVAL_DUPLICATE_BLOCKED"
    if exc.code in {
        "CANDIDATE_FINGERPRINT_CHANGED",
        "CANDIDATE_NOT_ACTIVE",
        "STRATEGY_REQUEST_NOT_APPROVED",
        "GENERATION_NOT_SUCCEEDED",
        "DRAFT_RUN_MISMATCH",
        "NO_SUCCESSFUL_ATTEMPT",
    }:
        return "STRATEGY_DRAFT_APPROVAL_INVALIDATED"
    return "STRATEGY_DRAFT_APPROVAL_REQUESTED"


@router.post(
    "/api/v1/admin/strategy-drafts/{draft_id}/approve", status_code=status.HTTP_201_CREATED
)
def approve_draft(
    draft_id: int,
    body: ApproveDraftBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    svc = StrategyDraftApprovalService(session)
    try:
        result = svc.approve(
            draft_id,
            actor=actor,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
            correlation_id=body.correlation_id,
        )
    except StrategyDraftApprovalError as exc:
        _audit(
            session,
            event_type=_duplicate_or_invalidation_event(exc),
            actor=actor,
            detail={"draft_id": draft_id, "code": exc.code, "message": exc.message},
        )
        _raise(exc)
        return {}

    _audit(
        session,
        event_type="STRATEGY_DRAFT_APPROVAL_REQUESTED",
        actor=actor,
        detail={"draft_id": draft_id, "approval_id": result.get("approval_id")},
    )
    if not result.get("idempotent_replay"):
        _audit(
            session,
            event_type="STRATEGY_DRAFT_APPROVED",
            actor=actor,
            detail={
                "approval_id": result.get("approval_id"),
                "draft_id": draft_id,
                "strategy_request_id": result.get("strategy_request_id"),
                "candidate_id": result.get("candidate_id"),
                "strategy_definition_id": result.get("strategy_definition_id"),
                "fingerprint": result.get("candidate_fingerprint_at_approval"),
                "definition_hash": result.get("definition_hash"),
                "result": "APPROVED",
                "reason": result.get("reason"),
            },
        )
        if result.get("strategy_definition_id"):
            _audit(
                session,
                event_type="STRATEGY_DEFINITION_CREATED",
                actor=actor,
                detail={
                    "strategy_definition_id": result.get("strategy_definition_id"),
                    "draft_id": draft_id,
                    "approval_id": result.get("approval_id"),
                    "definition_hash": result.get("definition_hash"),
                },
            )
    return result


@router.post(
    "/api/v1/admin/strategy-drafts/{draft_id}/reject", status_code=status.HTTP_201_CREATED
)
def reject_draft(
    draft_id: int,
    body: RejectDraftBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    svc = StrategyDraftApprovalService(session)
    try:
        result = svc.reject(
            draft_id,
            actor=actor,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
            correlation_id=body.correlation_id,
        )
    except StrategyDraftApprovalError as exc:
        _audit(
            session,
            event_type=_duplicate_or_invalidation_event(exc),
            actor=actor,
            detail={"draft_id": draft_id, "code": exc.code, "message": exc.message},
        )
        _raise(exc)
        return {}

    if not result.get("idempotent_replay"):
        _audit(
            session,
            event_type="STRATEGY_DRAFT_REJECTED",
            actor=actor,
            detail={
                "approval_id": result.get("approval_id"),
                "draft_id": draft_id,
                "result": "REJECTED",
                "reason": result.get("reason"),
            },
        )
    return result


@router.post(
    "/api/v1/admin/strategy-draft-approvals/{approval_id}/revoke",
)
def revoke_approval(
    approval_id: int,
    body: RevokeApprovalBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    svc = StrategyDraftApprovalService(session)
    try:
        result = svc.revoke(
            approval_id, actor=actor, reason=body.reason, correlation_id=body.correlation_id
        )
    except StrategyDraftApprovalError as exc:
        _raise(exc)
        return {}

    _audit(
        session,
        event_type="STRATEGY_DRAFT_APPROVAL_REVOKED",
        actor=actor,
        detail={
            "approval_id": approval_id,
            "draft_id": result.get("draft_id"),
            "strategy_definition_id": result.get("strategy_definition_id"),
            "reason": result.get("revoked_reason"),
        },
    )
    return result


@router.get("/api/v1/admin/strategy-draft-approvals")
def list_approvals(
    draft_id: int | None = Query(default=None),
    strategy_request_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return StrategyDraftApprovalService(session).list(
        draft_id=draft_id,
        strategy_request_id=strategy_request_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/api/v1/admin/strategy-draft-approvals/{approval_id}")
def get_approval(
    approval_id: int,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    svc = StrategyDraftApprovalService(session)
    try:
        result = svc.get(approval_id)
    except StrategyDraftApprovalError as exc:
        _raise(exc)
        return {}
    _audit(
        session,
        event_type="STRATEGY_DRAFT_APPROVAL_VIEWED",
        actor=admin_actor_label(admin),
        detail={"approval_id": approval_id},
    )
    return result


@router.get("/api/v1/admin/strategy-drafts/{draft_id}/approval")
def get_approval_for_draft(
    draft_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    result = StrategyDraftApprovalService(session).get_for_draft(draft_id)
    return result or {}


@router.get("/api/v1/admin/strategy-draft-approvals/{approval_id}/history")
def get_approval_history(
    approval_id: int,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    svc = StrategyDraftApprovalService(session)
    try:
        return svc.get_history(approval_id, limit=limit, offset=offset)
    except StrategyDraftApprovalError as exc:
        _raise(exc)
        return {}
