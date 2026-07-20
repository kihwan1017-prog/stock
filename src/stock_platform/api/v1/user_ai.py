"""사용자용 AI API — 상태·공시 요약·종목 추천 (STEP69/70).

관리자 Ollama Host/모델/settings API와 완전 분리.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.account_ownership import (
    assert_paper_account_access,
)
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.disclosure.disclosure_ai_summary_service import (
    DisclosureAiSummaryService,
)
from stock_platform.disclosure.user_disclosure_service import (
    UserDisclosureService,
)
from stock_platform.ai.user_ai_recommendation_service import (
    UserAiRateLimitError,
    UserAiRecommendationError,
    UserAiRecommendationService,
    UserAiUnavailableError,
)


router = APIRouter(
    prefix="/api/v1/user/ai",
    tags=["User AI"],
)


class CreateRecommendationBody(BaseModel):
    market_code: str = "KRX"
    account_id: int | None = None
    source_type: str = "WATCHLIST"
    recommendation_count: int = Field(default=5, ge=1, le=10)
    investment_horizon: str = "SHORT_TERM"
    risk_level: str = "MODERATE"


class FeedbackBody(BaseModel):
    feedback_type: str
    comment: str | None = Field(default=None, max_length=500)


def _rec(session: Session) -> UserAiRecommendationService:
    return UserAiRecommendationService(session)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, UserAiRateLimitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "AI_RECOMMENDATION_RATE_LIMITED",
                "message": str(exc),
                "retry_after_seconds": 120,
            },
        )
    if isinstance(exc, UserAiUnavailableError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    message = str(exc)
    code = (
        status.HTTP_404_NOT_FOUND
        if "찾을 수 없" in message
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=message)


@router.get("/status")
def user_ai_status(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    """관리자 Host/모델 목록 없이 사용 가능 여부만 반환."""

    _ = user
    rec = _rec(session).availability()
    disclosure = DisclosureAiSummaryService(session).availability()
    available = bool(rec.get("available")) and bool(
        disclosure.get("disclosure_summary_available")
        or disclosure.get("model_configured")
        or rec.get("model_configured")
    )
    # 추천 모델만 있어도 available
    available = bool(rec.get("available"))
    return {
        "available": available,
        "status": "AVAILABLE" if available else "UNAVAILABLE",
        "message": rec.get("message"),
        "active_model_display_name": rec.get("active_model_display_name"),
        "last_success_at": rec.get("last_success_at"),
        "retry_after_seconds": None,
        "disclosure_summary_available": disclosure.get(
            "disclosure_summary_available"
        ),
        "recommendation_available": available,
        "model_configured": rec.get("model_configured"),
        "prompt_version": rec.get("prompt_version"),
    }


@router.get("/disclosure-summaries/recent")
def recent_disclosure_summaries(
    limit: int = Query(10, ge=1, le=50),
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return UserDisclosureService(session).recent_ai_summaries(
        user.user_id, limit=limit
    )


@router.post("/recommendations")
async def create_recommendation(
    body: CreateRecommendationBody,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    if body.account_id is not None:
        assert_paper_account_access(user, body.account_id, session)
    service = _rec(session)
    try:
        return await service.create_recommendation(
            user.user_id,
            market_code=body.market_code,
            account_id=body.account_id,
            source_type=body.source_type,
            recommendation_count=body.recommendation_count,
            investment_horizon=body.investment_horizon,
            risk_level=body.risk_level,
        )
    except (
        UserAiRecommendationError,
        UserAiUnavailableError,
        UserAiRateLimitError,
    ) as exc:
        raise _http(exc) from exc
    finally:
        await service.aclose()


@router.get("/recommendations")
def list_recommendations(
    market_code: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    bookmarked: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _rec(session).list_recommendations(
            user.user_id,
            market_code=market_code,
            status=status_filter,
            bookmarked=bookmarked,
            page=page,
            page_size=page_size,
        )
    except UserAiRecommendationError as exc:
        raise _http(exc) from exc


@router.get("/recommendations/latest")
def latest_recommendation(
    market_code: str | None = None,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    result = _rec(session).latest(
        user.user_id, market_code=market_code
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="완료된 추천이 없습니다.",
        )
    return result


@router.get("/recommendations/{request_id}")
def get_recommendation(
    request_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _rec(session).get_detail(user.user_id, request_id)
    except UserAiRecommendationError as exc:
        raise _http(exc) from exc


@router.post("/recommendations/{request_id}/bookmark")
def bookmark_recommendation(
    request_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _rec(session).mark_bookmark(
            user.user_id, request_id, bookmarked=True
        )
    except UserAiRecommendationError as exc:
        raise _http(exc) from exc


@router.delete("/recommendations/{request_id}/bookmark")
def unbookmark_recommendation(
    request_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _rec(session).mark_bookmark(
            user.user_id, request_id, bookmarked=False
        )
    except UserAiRecommendationError as exc:
        raise _http(exc) from exc


@router.post("/recommendations/{request_id}/hide")
def hide_recommendation(
    request_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _rec(session).hide(user.user_id, request_id)
    except UserAiRecommendationError as exc:
        raise _http(exc) from exc


@router.post("/recommendations/{request_id}/feedback")
def feedback_recommendation(
    request_id: int,
    body: FeedbackBody,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _rec(session).feedback(
            user.user_id,
            request_id,
            feedback_type=body.feedback_type,
            comment=body.comment,
        )
    except UserAiRecommendationError as exc:
        raise _http(exc) from exc
