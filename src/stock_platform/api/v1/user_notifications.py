"""회원 Notification Center API — STEP71."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.notification.inbox_service import (
    NotificationInboxService,
    UserNotificationError,
)


router = APIRouter(
    prefix="/api/v1/user/notifications",
    tags=["User Notifications"],
)


class SubscriptionUpdateBody(BaseModel):
    event_type: str
    enabled: bool = True
    telegram_enabled: bool = False
    web_enabled: bool = True
    email_enabled: bool = False
    quiet_time_start: str | None = Field(default=None, max_length=5)
    quiet_time_end: str | None = Field(default=None, max_length=5)


def _svc(session: Session) -> NotificationInboxService:
    return NotificationInboxService(session)


def _http(exc: UserNotificationError) -> HTTPException:
    message = str(exc)
    code = (
        status.HTTP_404_NOT_FOUND
        if "찾을 수 없" in message
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=message)


@router.get("")
def list_notifications(
    event_type: str | None = None,
    severity: str | None = None,
    unread_only: bool = False,
    archived: bool | None = False,
    starred: bool | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return _svc(session).list_notifications(
        user.user_id,
        event_type=event_type,
        severity=severity,
        unread_only=unread_only,
        archived=archived,
        starred=starred,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.get("/unread-count")
def unread_count(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return _svc(session).unread_count(user.user_id)


@router.get("/subscriptions")
def list_subscriptions(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return _svc(session).list_subscriptions(user.user_id)


@router.put("/subscriptions")
def update_subscription(
    body: SubscriptionUpdateBody,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return _svc(session).update_subscription(
        user.user_id,
        event_type=body.event_type,
        enabled=body.enabled,
        telegram_enabled=body.telegram_enabled,
        web_enabled=body.web_enabled,
        email_enabled=body.email_enabled,
        quiet_time_start=body.quiet_time_start,
        quiet_time_end=body.quiet_time_end,
    )


@router.post("/read-all")
def read_all(
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    return _svc(session).read_all(user.user_id)


@router.get("/{notification_id}")
def get_notification(
    notification_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).get_detail(user.user_id, notification_id)
    except UserNotificationError as exc:
        raise _http(exc) from exc


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).mark_read(
            user.user_id, notification_id, read=True
        )
    except UserNotificationError as exc:
        raise _http(exc) from exc


@router.delete("/{notification_id}/read")
def mark_unread(
    notification_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).mark_read(
            user.user_id, notification_id, read=False
        )
    except UserNotificationError as exc:
        raise _http(exc) from exc


@router.post("/{notification_id}/archive")
def archive(
    notification_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).mark_archived(
            user.user_id, notification_id, archived=True
        )
    except UserNotificationError as exc:
        raise _http(exc) from exc


@router.delete("/{notification_id}/archive")
def unarchive(
    notification_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).mark_archived(
            user.user_id, notification_id, archived=False
        )
    except UserNotificationError as exc:
        raise _http(exc) from exc


@router.post("/{notification_id}/star")
def star(
    notification_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).mark_starred(
            user.user_id, notification_id, starred=True
        )
    except UserNotificationError as exc:
        raise _http(exc) from exc


@router.delete("/{notification_id}/star")
def unstar(
    notification_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).mark_starred(
            user.user_id, notification_id, starred=False
        )
    except UserNotificationError as exc:
        raise _http(exc) from exc


@router.delete("/{notification_id}")
def delete_notification(
    notification_id: int,
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    try:
        return _svc(session).soft_delete(user.user_id, notification_id)
    except UserNotificationError as exc:
        raise _http(exc) from exc
