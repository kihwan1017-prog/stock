"""회원 Preferences API — STEP72.

관리자 `/api/v1/settings` 와 분리. settings:read/write 불필요.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.auth.preference_service import (
    DEFAULTS,
    UserPreferenceError,
    UserPreferenceService,
)
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/user/settings",
    tags=["User Settings"],
)


class UserSettingsBody(BaseModel):
    """PUT/PATCH 공통 본문 — 모든 필드 optional (PATCH), PUT은 서비스에서 기본값 보완."""

    model_config = ConfigDict(extra="forbid")

    theme: str | None = None
    language: str | None = None
    timezone: str | None = None
    date_format: str | None = None
    number_format: str | None = None
    currency: str | None = None
    default_market: str | None = None
    default_account_id: int | None = None
    default_watchlist_id: int | None = None
    default_dashboard: str | None = None
    items_per_page: int | None = Field(default=None, ge=5, le=100)
    ai_enabled: bool | None = None
    ai_auto_summary: bool | None = None
    ai_recommendation_enabled: bool | None = None
    notification_enabled: bool | None = None
    telegram_enabled: bool | None = None
    email_enabled: bool | None = None
    web_enabled: bool | None = None


def _svc(session: Session) -> UserPreferenceService:
    return UserPreferenceService(session)


def _http(exc: UserPreferenceError) -> HTTPException:
    message = str(exc)
    code = (
        status.HTTP_403_FORBIDDEN
        if "본인" in message or "권한" in message
        else status.HTTP_400_BAD_REQUEST
    )
    if "찾을 수 없" in message:
        code = status.HTTP_404_NOT_FOUND
    return HTTPException(status_code=code, detail=message)


def _body_dict(body: UserSettingsBody, *, include_nulls: bool) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if include_nulls:
        # PUT: 명시적으로 null 보낸 필드도 반영
        raw = body.model_dump(exclude_unset=False)
        for key in DEFAULTS:
            if key in body.model_fields_set:
                data[key] = raw[key]
    return data


@router.get("")
def get_settings(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return _svc(session).get_or_create(user.user_id)


@router.put("")
def put_settings(
    body: UserSettingsBody,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).update(
            user.user_id,
            _body_dict(body, include_nulls=True),
            replace=True,
        )
    except UserPreferenceError as exc:
        raise _http(exc) from exc


@router.patch("")
def patch_settings(
    body: UserSettingsBody,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    patch = _body_dict(body, include_nulls=False)
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="변경할 필드가 없습니다.",
        )
    try:
        return _svc(session).update(
            user.user_id, patch, replace=False
        )
    except UserPreferenceError as exc:
        raise _http(exc) from exc


@router.post("/reset")
def reset_settings(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return _svc(session).reset(user.user_id)
