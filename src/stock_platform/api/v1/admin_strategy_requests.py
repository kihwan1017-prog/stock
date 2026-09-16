"""STEP 12-1 — Admin Strategy Request API.

AI Candidate -> Strategy Request 승인 게이트의 관리자(심사자) 측 API.
승인/반려만 수행하며, 승인 이후 Strategy Draft 생성 등은 STEP12-2 이후
범위다. AI 호출, Broker/Order/Runtime/Scheduler WRITE 없음.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_generation.service import (
    StrategyDraftGenerationService,
)
from stock_platform.ai.strategy_request.constants import REVIEW_NOTE_MAX_LENGTH
from stock_platform.ai.strategy_request.service import (
    StrategyRequestError,
    StrategyRequestService,
)
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/strategy-requests",
    tags=["Admin Strategy Requests"],
    dependencies=[Depends(require_admin)],
)


class ReviewStrategyRequestBody(BaseModel):
    review_note: str | None = Field(default=None, max_length=REVIEW_NOTE_MAX_LENGTH)
    correlation_id: str | None = None


class RejectStrategyRequestBody(BaseModel):
    review_note: str = Field(min_length=1, max_length=REVIEW_NOTE_MAX_LENGTH)
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


def _raise(exc: StrategyRequestError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code in {"NOT_FOUND", "CANDIDATE_NOT_FOUND"}:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {"INVALID_STATE_TRANSITION", "CANDIDATE_NOT_ACTIVE_AT_REVIEW"}:
        code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.get("")
def list_strategy_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    candidate_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return StrategyRequestService(session).list(
        user_id=user_id,
        status=status_filter,
        candidate_id=candidate_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{strategy_request_id}")
def get_strategy_request(
    strategy_request_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        return StrategyRequestService(session).get(strategy_request_id)
    except StrategyRequestError as exc:
        _raise(exc)
    return {}


@router.get("/{strategy_request_id}/history")
def get_strategy_request_history(
    strategy_request_id: int,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        return StrategyRequestService(session).get_history(
            strategy_request_id, limit=limit, offset=offset
        )
    except StrategyRequestError as exc:
        _raise(exc)
    return {}


@router.post("/{strategy_request_id}/approve")
def approve_strategy_request(
    strategy_request_id: int,
    body: ReviewStrategyRequestBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    try:
        result = StrategyRequestService(session).approve(
            strategy_request_id,
            reviewer_user_id=admin.user_id,
            review_note=body.review_note,
            actor=actor,
            correlation_id=body.correlation_id,
        )
    except StrategyRequestError as exc:
        _audit(
            session,
            event_type="STRATEGY_REQUEST_APPROVE_FAILED",
            actor=actor,
            detail={
                "strategy_request_id": strategy_request_id,
                "code": exc.code,
                "message": exc.message,
            },
        )
        _raise(exc)
        return {}
    _audit(
        session,
        event_type="STRATEGY_REQUEST_APPROVED",
        actor=actor,
        detail={
            "strategy_request_id": strategy_request_id,
            "candidate_id": result.get("candidate_id"),
            "review_note": body.review_note,
        },
    )
    return result


@router.post("/{strategy_request_id}/reject")
def reject_strategy_request(
    strategy_request_id: int,
    body: RejectStrategyRequestBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    try:
        result = StrategyRequestService(session).reject(
            strategy_request_id,
            reviewer_user_id=admin.user_id,
            review_note=body.review_note,
            actor=actor,
            correlation_id=body.correlation_id,
        )
    except StrategyRequestError as exc:
        _audit(
            session,
            event_type="STRATEGY_REQUEST_REJECT_FAILED",
            actor=actor,
            detail={
                "strategy_request_id": strategy_request_id,
                "code": exc.code,
                "message": exc.message,
            },
        )
        _raise(exc)
        return {}
    _audit(
        session,
        event_type="STRATEGY_REQUEST_REJECTED",
        actor=actor,
        detail={
            "strategy_request_id": strategy_request_id,
            "candidate_id": result.get("candidate_id"),
            "review_note": body.review_note,
        },
    )
    return result


@router.get("/{strategy_request_id}/draft-timeline")
def get_draft_timeline(
    strategy_request_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """STEP12-2-3 — Draft History + Generation Run을 시간순으로 병합한 Timeline(§4/§12).

    기존 서비스(StrategyDraftService.get_history, StrategyDraftGenerationService
    .list_generation_runs)를 그대로 재사용해 조합만 한다 — 신규 도메인/테이블 없음.
    """
    try:
        StrategyRequestService(session).get(strategy_request_id)
    except StrategyRequestError as exc:
        _raise(exc)
        return {}

    draft_svc = StrategyDraftService(session)
    drafts = draft_svc.list(strategy_request_id=strategy_request_id, limit=200)["items"]

    events: list[dict[str, Any]] = []
    for d in drafts:
        history = draft_svc.get_history(d["draft_id"], limit=200)["items"]
        for h in history:
            events.append(
                {
                    "type": "DRAFT_HISTORY",
                    "action": h["action"],
                    "draft_id": d["draft_id"],
                    "label": d["label"],
                    "previous_status": h["previous_status"],
                    "new_status": h["new_status"],
                    "actor": h["actor"],
                    "occurred_at": h["created_at"],
                }
            )

    gen_svc = StrategyDraftGenerationService(session)
    runs = gen_svc.list_generation_runs(
        strategy_request_id=strategy_request_id, limit=200
    )["items"]
    for r in runs:
        events.append(
            {
                "type": "GENERATION_REQUESTED",
                "generation_run_id": r["generation_run_id"],
                "provider": r["provider"],
                "model": r["model"],
                "retry_of_run_id": r["retry_of_run_id"],
                "occurred_at": r["created_at"],
            }
        )
        if r["started_at"]:
            events.append(
                {
                    "type": "GENERATION_STARTED",
                    "generation_run_id": r["generation_run_id"],
                    "occurred_at": r["started_at"],
                }
            )
        if r["completed_at"]:
            events.append(
                {
                    "type": f"GENERATION_{r['status']}",
                    "generation_run_id": r["generation_run_id"],
                    "draft_id": r["draft_id"],
                    "error_code": r["error_code"],
                    "occurred_at": r["completed_at"],
                }
            )

    events.sort(key=lambda e: e["occurred_at"])
    return {"strategy_request_id": strategy_request_id, "items": events}
