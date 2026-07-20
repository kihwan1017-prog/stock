"""회원 관심종목 공시 API — STEP69."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.disclosure.disclosure_ai_summary_service import (
    DisclosureAiRateLimitError,
    DisclosureAiSummaryService,
    DisclosureAiUnavailableError,
)
from stock_platform.disclosure.user_disclosure_service import (
    UserDisclosureError,
    UserDisclosureService,
)


router = APIRouter(
    prefix="/api/v1/user/disclosures",
    tags=["User Disclosures"],
)


def _svc(session: Session) -> UserDisclosureService:
    return UserDisclosureService(session)


def _ai(session: Session) -> DisclosureAiSummaryService:
    return DisclosureAiSummaryService(session)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, DisclosureAiRateLimitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        )
    if isinstance(exc, DisclosureAiUnavailableError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    message = str(exc)
    code = (
        status.HTTP_404_NOT_FOUND
        if "찾을 수 없" in message or "연결되지 않은" in message
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=message)


@router.get("")
def list_user_disclosures(
    market_code: str | None = None,
    symbol: str | None = None,
    watchlist_id: int | None = None,
    disclosure_type: str | None = None,
    report_name: str | None = None,
    keyword: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    read_status: str | None = Query(None),
    bookmarked: bool | None = None,
    has_ai_summary: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).list_disclosures(
            user.user_id,
            market_code=market_code,
            symbol=symbol,
            watchlist_id=watchlist_id,
            disclosure_type=disclosure_type,
            report_name=report_name,
            keyword=keyword,
            from_date=from_date,
            to_date=to_date,
            read_status=read_status,
            bookmarked=bookmarked,
            has_ai_summary=has_ai_summary,
            page=page,
            page_size=page_size,
        )
    except UserDisclosureError as exc:
        raise _http(exc) from exc


@router.get("/unread-count")
def get_unread_count(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return _svc(session).unread_count(user.user_id)


@router.get("/ai-summaries/recent")
def recent_ai_summaries(
    limit: int = Query(10, ge=1, le=50),
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return _svc(session).recent_ai_summaries(user.user_id, limit=limit)


@router.post("/read-all")
def read_all(
    market_code: str | None = None,
    symbol: str | None = None,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).read_all(
            user.user_id,
            market_code=market_code,
            symbol=symbol,
        )
    except UserDisclosureError as exc:
        raise _http(exc) from exc


@router.get("/{disclosure_id}")
def get_detail(
    disclosure_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).get_detail(user.user_id, disclosure_id)
    except UserDisclosureError as exc:
        raise _http(exc) from exc


@router.post("/{disclosure_id}/read")
def mark_read(
    disclosure_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).mark_read(
            user.user_id, disclosure_id, read=True
        )
    except UserDisclosureError as exc:
        raise _http(exc) from exc


@router.delete("/{disclosure_id}/read")
def unmark_read(
    disclosure_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).mark_read(
            user.user_id, disclosure_id, read=False
        )
    except UserDisclosureError as exc:
        raise _http(exc) from exc


@router.post("/{disclosure_id}/bookmark")
def bookmark(
    disclosure_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).mark_bookmark(
            user.user_id, disclosure_id, bookmarked=True
        )
    except UserDisclosureError as exc:
        raise _http(exc) from exc


@router.delete("/{disclosure_id}/bookmark")
def unbookmark(
    disclosure_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).mark_bookmark(
            user.user_id, disclosure_id, bookmarked=False
        )
    except UserDisclosureError as exc:
        raise _http(exc) from exc


@router.get("/{disclosure_id}/ai-summary")
def get_ai_summary(
    disclosure_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _ai(session).get_summary(user.user_id, disclosure_id)
    except UserDisclosureError as exc:
        raise _http(exc) from exc


@router.post("/{disclosure_id}/ai-summary")
async def request_ai_summary(
    disclosure_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    service = _ai(session)
    try:
        return await service.request_summary(
            user.user_id, disclosure_id, regenerate=False
        )
    except (
        UserDisclosureError,
        DisclosureAiUnavailableError,
        DisclosureAiRateLimitError,
    ) as exc:
        raise _http(exc) from exc
    finally:
        await service.aclose()


@router.post("/{disclosure_id}/ai-summary/regenerate")
async def regenerate_ai_summary(
    disclosure_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    service = _ai(session)
    try:
        return await service.request_summary(
            user.user_id, disclosure_id, regenerate=True
        )
    except (
        UserDisclosureError,
        DisclosureAiUnavailableError,
        DisclosureAiRateLimitError,
    ) as exc:
        raise _http(exc) from exc
    finally:
        await service.aclose()
