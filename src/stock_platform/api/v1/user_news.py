"""회원 관심종목 뉴스 API — STEP68."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.news.user_news_service import (
    UserNewsError,
    UserNewsService,
)


router = APIRouter(
    prefix="/api/v1/user/news",
    tags=["User News"],
)


def _service(session: Session) -> UserNewsService:
    return UserNewsService(session)


def _http(exc: UserNewsError) -> HTTPException:
    message = str(exc)
    code = (
        status.HTTP_404_NOT_FOUND
        if "찾을 수 없" in message or "연결되지 않은" in message
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=message)


@router.get("")
def list_user_news(
    market_code: str | None = None,
    symbol: str | None = None,
    watchlist_id: int | None = None,
    keyword: str | None = None,
    source_code: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    read_status: str | None = Query(
        None,
        description="read | unread | 생략=전체",
    ),
    bookmarked: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """관심종목(news_enabled) 뉴스 목록. user_id는 JWT만 사용."""

    try:
        return _service(session).list_news(
            user.user_id,
            market_code=market_code,
            symbol=symbol,
            watchlist_id=watchlist_id,
            keyword=keyword,
            source_code=source_code,
            from_date=from_date,
            to_date=to_date,
            read_status=read_status,
            bookmarked=bookmarked,
            page=page,
            page_size=page_size,
        )
    except UserNewsError as exc:
        raise _http(exc) from exc


@router.get("/unread-count")
def get_unread_count(
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    return _service(session).unread_count(user.user_id)


@router.post("/read-all")
def read_all_news(
    market_code: str | None = None,
    symbol: str | None = None,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """관심종목 미읽음 뉴스 전체 읽음 처리."""

    try:
        return _service(session).read_all(
            user.user_id,
            market_code=market_code,
            symbol=symbol,
        )
    except UserNewsError as exc:
        raise _http(exc) from exc


@router.get("/{news_id}")
def get_user_news_detail(
    news_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).get_detail(user.user_id, news_id)
    except UserNewsError as exc:
        raise _http(exc) from exc


@router.post("/{news_id}/read")
def mark_news_read(
    news_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).mark_read(
            user.user_id, news_id, read=True
        )
    except UserNewsError as exc:
        raise _http(exc) from exc


@router.delete("/{news_id}/read")
def unmark_news_read(
    news_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).mark_read(
            user.user_id, news_id, read=False
        )
    except UserNewsError as exc:
        raise _http(exc) from exc


@router.post("/{news_id}/bookmark")
def bookmark_news(
    news_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).mark_bookmark(
            user.user_id, news_id, bookmarked=True
        )
    except UserNewsError as exc:
        raise _http(exc) from exc


@router.delete("/{news_id}/bookmark")
def unbookmark_news(
    news_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).mark_bookmark(
            user.user_id, news_id, bookmarked=False
        )
    except UserNewsError as exc:
        raise _http(exc) from exc
