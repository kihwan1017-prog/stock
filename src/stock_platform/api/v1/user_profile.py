"""회원 Self Profile API — STEP73.

관리자 `/api/v1/users` 와 분리. Path/Body의 user_id 를 받지 않음.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import AuditLogService, get_audit_service
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.auth.profile_service import (
    UserProfileError,
    UserProfileService,
)
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/user/profile",
    tags=["User Profile"],
)


class ProfileUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=100)
    nickname: str | None = Field(default=None, max_length=50)
    profile_image_url: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=500)
    locale: str | None = Field(default=None, max_length=10)


class ChangePasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    new_password_confirmation: str = Field(min_length=8, max_length=128)


def _svc(session: Session) -> UserProfileService:
    return UserProfileService(session)


def _http(exc: UserProfileError) -> HTTPException:
    message = str(exc)
    code = status.HTTP_400_BAD_REQUEST
    if "찾을 수 없" in message:
        code = status.HTTP_404_NOT_FOUND
    if "현재 비밀번호" in message:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=message)


@router.get("")
def get_profile(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).get_profile(user.user_id)
    except UserProfileError as exc:
        raise _http(exc) from exc


@router.patch("")
def patch_profile(
    body: ProfileUpdateBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    patch = body.model_dump(exclude_unset=True)
    try:
        result = _svc(session).update_profile(user.user_id, patch)
        audit.record(
            event_type="USER_PROFILE_UPDATED",
            actor=user.username,
            detail={"fields": sorted(patch.keys()), "user_id": user.user_id},
        )
        session.commit()
        return result
    except UserProfileError as exc:
        session.rollback()
        raise _http(exc) from exc


@router.post("/change-password")
def change_password(
    body: ChangePasswordBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
    x_refresh_token: str | None = Header(default=None, alias="X-Refresh-Token"),
):
    enforce_rate_limit(
        request,
        scope="user_change_password",
        limit=10,
        window_seconds=300,
    )
    try:
        result = _svc(session).change_password(
            user.user_id,
            current_password=body.current_password,
            new_password=body.new_password,
            new_password_confirmation=body.new_password_confirmation,
            current_refresh_token=x_refresh_token,
        )
        audit.record(
            event_type="AUTH_PASSWORD_CHANGED",
            actor=user.username,
            detail={
                "user_id": user.user_id,
                "revoked_session_count": result["revoked_session_count"],
                "current_session_kept": result["current_session_kept"],
            },
        )
        session.commit()
        return result
    except UserProfileError as exc:
        session.rollback()
        try:
            AuditLogService(session).record(
                event_type="AUTH_PASSWORD_CHANGE_FAILED",
                actor=user.username,
                detail={"user_id": user.user_id},
            )
            session.commit()
        except Exception:
            session.rollback()
        raise _http(exc) from exc


@router.get("/sessions")
def list_sessions(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
    x_refresh_token: str | None = Header(default=None, alias="X-Refresh-Token"),
):
    return _svc(session).list_sessions(
        user.user_id, current_refresh_token=x_refresh_token
    )


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: str,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
    x_refresh_token: str | None = Header(default=None, alias="X-Refresh-Token"),
):
    try:
        result = _svc(session).revoke_session(
            user.user_id,
            session_id,
            current_refresh_token=x_refresh_token,
        )
        audit.record(
            event_type="AUTH_SESSION_REVOKED",
            actor=user.username,
            detail={
                "session_id": session_id,
                "was_current": result["was_current"],
            },
        )
        session.commit()
        return result
    except UserProfileError as exc:
        session.rollback()
        raise _http(exc) from exc


@router.delete("/sessions")
def revoke_sessions(
    request: Request,
    exclude_current: bool = Query(True),
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
    x_refresh_token: str | None = Header(default=None, alias="X-Refresh-Token"),
):
    enforce_rate_limit(
        request,
        scope="user_revoke_sessions",
        limit=10,
        window_seconds=300,
    )
    result = _svc(session).revoke_sessions(
        user.user_id,
        exclude_current=exclude_current,
        current_refresh_token=x_refresh_token,
    )
    audit.record(
        event_type="AUTH_SESSIONS_REVOKED",
        actor=user.username,
        detail=result,
    )
    session.commit()
    return result


@router.get("/accounts-summary")
def accounts_summary(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return _svc(session).accounts_summary(user.user_id)


@router.get("/connections")
def list_connections(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return _svc(session).list_connections(user.user_id)


@router.delete("/connections/telegram")
def disconnect_telegram(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = _svc(session).disconnect_telegram(user.user_id)
    audit.record(
        event_type="USER_TELEGRAM_DISCONNECTED",
        actor=user.username,
        detail={"user_id": user.user_id},
    )
    session.commit()
    return result
