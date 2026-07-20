"""회원 관심종목 API — STEP67."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.trading.watchlist_service import (
    WatchlistError,
    WatchlistService,
)


router = APIRouter(
    prefix="/api/v1/user/watchlist",
    tags=["User Watchlist"],
)


class CreateWatchlistRequest(BaseModel):
    market: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    symbol_name: str | None = Field(default=None, max_length=200)
    memo: str | None = Field(default=None, max_length=500)
    color: str | None = Field(default=None, max_length=20)
    alarm_enabled: bool = False
    news_enabled: bool = True
    disclosure_enabled: bool = True
    ai_enabled: bool = True


class UpdateWatchlistRequest(BaseModel):
    memo: str | None = Field(default=None, max_length=500)
    color: str | None = Field(default=None, max_length=20)
    symbol_name: str | None = Field(default=None, max_length=200)
    alarm_enabled: bool | None = None
    news_enabled: bool | None = None
    disclosure_enabled: bool | None = None
    ai_enabled: bool | None = None
    display_order: int | None = None
    clear_memo: bool = False
    clear_color: bool = False


class ReorderWatchlistRequest(BaseModel):
    ordered_ids: list[int] = Field(min_length=1)


def _service(session: Session) -> WatchlistService:
    return WatchlistService(session)


def _http(exc: WatchlistError) -> HTTPException:
    message = str(exc)
    if "찾을 수 없" in message:
        code = status.HTTP_404_NOT_FOUND
    elif "이미 등록" in message or "최대" in message:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=message)


@router.get("")
def list_watchlist(
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """로그인 사용자 본인 관심종목만 반환."""

    return _service(session).list_items(user.user_id)


@router.get("/search")
def search_watchlist_symbols(
    q: str = Query(..., min_length=1, max_length=100),
    market: str | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """종목 자동완성 검색 (코드·이름)."""

    _ = user
    return {
        "items": _service(session).search_symbols(
            query=q,
            market=market,
            limit=limit,
        ),
        "query": q,
    }


@router.post("")
def create_watchlist_item(
    request: CreateWatchlistRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).add_item(
            user.user_id,
            market=request.market,
            symbol=request.symbol,
            symbol_name=request.symbol_name,
            memo=request.memo,
            color=request.color,
            alarm_enabled=request.alarm_enabled,
            news_enabled=request.news_enabled,
            disclosure_enabled=request.disclosure_enabled,
            ai_enabled=request.ai_enabled,
        )
    except WatchlistError as exc:
        raise _http(exc) from exc


@router.patch("/{watchlist_id}")
def update_watchlist_item(
    watchlist_id: int,
    request: UpdateWatchlistRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).update_item(
            user.user_id,
            watchlist_id,
            memo=request.memo,
            color=request.color,
            symbol_name=request.symbol_name,
            alarm_enabled=request.alarm_enabled,
            news_enabled=request.news_enabled,
            disclosure_enabled=request.disclosure_enabled,
            ai_enabled=request.ai_enabled,
            display_order=request.display_order,
            clear_memo=request.clear_memo,
            clear_color=request.clear_color,
        )
    except WatchlistError as exc:
        raise _http(exc) from exc


@router.delete("/{watchlist_id}")
def delete_watchlist_item(
    watchlist_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).delete_item(
            user.user_id, watchlist_id
        )
    except WatchlistError as exc:
        raise _http(exc) from exc


@router.put("/reorder")
def reorder_watchlist(
    request: ReorderWatchlistRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).reorder(
            user.user_id, request.ordered_ids
        )
    except WatchlistError as exc:
        raise _http(exc) from exc
