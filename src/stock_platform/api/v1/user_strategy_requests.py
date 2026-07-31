"""STEP 12-1 — User Strategy Request API.

AI Candidate -> Strategy Request 승인 게이트의 사용자(요청자) 측 API.
Strategy Draft 생성, Backtest, 실거래 승인 등은 다루지 않는다
(STEP12-2 이후). AI 호출, Broker/Order/Runtime/Scheduler WRITE 없음.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.ai.strategy_request.constants import REQUEST_REASON_MAX_LENGTH
from stock_platform.ai.strategy_request.service import (
    StrategyRequestError,
    StrategyRequestService,
)
from stock_platform.api.deps_admin import AuditLogService
from stock_platform.auth.deps import AuthenticatedUser, require_permission
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/user/strategy-requests",
    tags=["User Strategy Requests"],
)


class CreateStrategyRequestBody(BaseModel):
    candidate_id: int = Field(gt=0)
    request_note: str | None = Field(
        default=None, max_length=REQUEST_REASON_MAX_LENGTH
    )
    correlation_id: str | None = None


class CancelStrategyRequestBody(BaseModel):
    reason: str | None = Field(default=None, max_length=REQUEST_REASON_MAX_LENGTH)
    correlation_id: str | None = None


def _actor(user: AuthenticatedUser) -> str:
    return f"user:{user.user_id}"


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
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    elif exc.code == "OWNERSHIP_DENIED":
        code = status.HTTP_403_FORBIDDEN
    elif exc.code in {"CANDIDATE_NOT_ACTIVE", "DUPLICATE_ACTIVE_REQUEST"}:
        code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_strategy_request(
    body: CreateStrategyRequestBody,
    http_request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_permission("trading:write")),
) -> dict[str, Any]:
    enforce_rate_limit(
        http_request,
        scope="strategy_request_create",
        limit=30,
        window_seconds=60,
    )
    actor = _actor(user)
    try:
        result = StrategyRequestService(session).create(
            candidate_id=body.candidate_id,
            user_id=user.user_id,
            request_note=body.request_note,
            actor=actor,
            correlation_id=body.correlation_id,
        )
    except StrategyRequestError as exc:
        _audit(
            session,
            event_type="STRATEGY_REQUEST_CREATE_FAILED",
            actor=actor,
            detail={
                "candidate_id": body.candidate_id,
                "code": exc.code,
                "message": exc.message,
            },
        )
        _raise(exc)
        return {}
    _audit(
        session,
        event_type="STRATEGY_REQUEST_CREATED",
        actor=actor,
        detail={
            "strategy_request_id": result.get("strategy_request_id"),
            "candidate_id": body.candidate_id,
        },
    )
    return result


@router.get("")
def list_strategy_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
    # STEP12-2-2: 조회 전용 API인데 trading:write(쓰기 권한)를 요구하던
    # STEP12-1의 RBAC 오적용을 trading:read로 수정(strategy_drafts의
    # 동일 결함을 STEP12-2-1A에서 고친 것과 동일한 프로젝트 컨벤션 적용).
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
) -> dict[str, Any]:
    # IDOR 방지 — user_id를 요청자 본인으로 고정(쿼리 파라미터로 타인 지정 불가)
    return StrategyRequestService(session).list(
        user_id=user.user_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/{strategy_request_id}")
def get_strategy_request(
    strategy_request_id: int,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
) -> dict[str, Any]:
    try:
        return StrategyRequestService(session).get_owned(
            strategy_request_id, user_id=user.user_id
        )
    except StrategyRequestError as exc:
        _raise(exc)
    return {}


@router.post("/{strategy_request_id}/cancel")
def cancel_strategy_request(
    strategy_request_id: int,
    body: CancelStrategyRequestBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_permission("trading:write")),
) -> dict[str, Any]:
    actor = _actor(user)
    try:
        result = StrategyRequestService(session).cancel(
            strategy_request_id,
            user_id=user.user_id,
            reason=body.reason,
            actor=actor,
            correlation_id=body.correlation_id,
        )
    except StrategyRequestError as exc:
        _audit(
            session,
            event_type="STRATEGY_REQUEST_CANCEL_FAILED",
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
        event_type="STRATEGY_REQUEST_CANCELLED",
        actor=actor,
        detail={"strategy_request_id": strategy_request_id},
    )
    return result
