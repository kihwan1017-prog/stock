"""STEP 11-13 — User AI Candidate Lifecycle API (read-only).

Promotion으로 등록된 Candidate는 플랫폼 참조용 — user_id 소유권 없음.
인증된 사용자에게 lifecycle·provenance·history 조회만 허용.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.service import (
    AICandidateLifecycleError,
    AICandidateLifecycleService,
)
from stock_platform.auth.deps import AuthenticatedUser, get_current_user
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/user/ai-candidates",
    tags=["User AI Candidate Lifecycle"],
)


def _raise(exc: AICandidateLifecycleError) -> None:
    from fastapi import HTTPException, status

    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.get("/{candidate_id}/lifecycle")
def get_lifecycle(
    candidate_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return AICandidateLifecycleService(session).get(candidate_id)
    except AICandidateLifecycleError as exc:
        _raise(exc)
    return {}


@router.get("/{candidate_id}/provenance")
def get_provenance(
    candidate_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return AICandidateLifecycleService(session).get_provenance(candidate_id)
    except AICandidateLifecycleError as exc:
        _raise(exc)
    return {}


@router.get("/{candidate_id}/history")
def get_history(
    candidate_id: int,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return AICandidateLifecycleService(session).get_history(
            candidate_id, limit=min(limit, 200), offset=offset
        )
    except AICandidateLifecycleError as exc:
        _raise(exc)
    return {}
