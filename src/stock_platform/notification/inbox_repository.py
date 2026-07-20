"""Notification Center Repository — STEP71."""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from stock_platform.notification.inbox_models import (
    Notification,
    NotificationSubscription,
    UserNotification,
)


class NotificationInboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_notification(self, row: Notification) -> Notification:
        self._session.add(row)
        self._session.flush()
        return row

    def find_by_dedupe(self, dedupe_key: str) -> Notification | None:
        if not dedupe_key:
            return None
        return self._session.scalar(
            select(Notification)
            .where(Notification.dedupe_key == dedupe_key)
            .order_by(Notification.notification_id.desc())
            .limit(1)
        )

    def add_user_notification(
        self, row: UserNotification
    ) -> UserNotification:
        self._session.add(row)
        self._session.flush()
        return row

    def get_user_link(
        self, *, user_id: int, notification_id: int
    ) -> UserNotification | None:
        return self._session.scalar(
            select(UserNotification).where(
                UserNotification.user_id == user_id,
                UserNotification.notification_id == notification_id,
                UserNotification.is_deleted.is_(False),
            )
        )

    def get_owned(
        self, *, user_id: int, notification_id: int
    ) -> tuple[UserNotification, Notification] | None:
        stmt = (
            select(UserNotification, Notification)
            .join(
                Notification,
                Notification.notification_id
                == UserNotification.notification_id,
            )
            .where(
                UserNotification.user_id == user_id,
                UserNotification.notification_id == notification_id,
                UserNotification.is_deleted.is_(False),
            )
        )
        row = self._session.execute(stmt).first()
        return (row[0], row[1]) if row else None

    def list_for_user(
        self,
        *,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        event_type: str | None = None,
        severity: str | None = None,
        unread_only: bool = False,
        archived: bool | None = None,
        starred: bool | None = None,
        keyword: str | None = None,
    ) -> list[tuple[UserNotification, Notification]]:
        stmt = (
            select(UserNotification, Notification)
            .join(
                Notification,
                Notification.notification_id
                == UserNotification.notification_id,
            )
            .where(
                UserNotification.user_id == user_id,
                UserNotification.is_deleted.is_(False),
            )
        )
        if unread_only:
            stmt = stmt.where(UserNotification.is_read.is_(False))
        if archived is True:
            stmt = stmt.where(UserNotification.is_archived.is_(True))
        elif archived is False:
            stmt = stmt.where(UserNotification.is_archived.is_(False))
        if starred is True:
            stmt = stmt.where(UserNotification.is_starred.is_(True))
        if event_type:
            stmt = stmt.where(
                Notification.event_type == event_type.upper()
            )
        if severity:
            stmt = stmt.where(Notification.severity == severity.upper())
        if keyword:
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    Notification.title.ilike(pattern),
                    Notification.message.ilike(pattern),
                )
            )
        stmt = (
            stmt.order_by(
                UserNotification.created_at.desc(),
                UserNotification.user_notification_id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.execute(stmt).all())

    def count_for_user(
        self,
        *,
        user_id: int,
        event_type: str | None = None,
        severity: str | None = None,
        unread_only: bool = False,
        archived: bool | None = None,
        starred: bool | None = None,
        keyword: str | None = None,
    ) -> int:
        stmt = (
            select(func.count(UserNotification.user_notification_id))
            .select_from(UserNotification)
            .join(
                Notification,
                Notification.notification_id
                == UserNotification.notification_id,
            )
            .where(
                UserNotification.user_id == user_id,
                UserNotification.is_deleted.is_(False),
            )
        )
        if unread_only:
            stmt = stmt.where(UserNotification.is_read.is_(False))
        if archived is True:
            stmt = stmt.where(UserNotification.is_archived.is_(True))
        elif archived is False:
            stmt = stmt.where(UserNotification.is_archived.is_(False))
        if starred is True:
            stmt = stmt.where(UserNotification.is_starred.is_(True))
        if event_type:
            stmt = stmt.where(
                Notification.event_type == event_type.upper()
            )
        if severity:
            stmt = stmt.where(Notification.severity == severity.upper())
        if keyword:
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    Notification.title.ilike(pattern),
                    Notification.message.ilike(pattern),
                )
            )
        return int(self._session.scalar(stmt) or 0)

    def unread_count(self, user_id: int) -> int:
        return int(
            self._session.scalar(
                select(func.count(UserNotification.user_notification_id)).where(
                    UserNotification.user_id == user_id,
                    UserNotification.is_deleted.is_(False),
                    UserNotification.is_archived.is_(False),
                    UserNotification.is_read.is_(False),
                )
            )
            or 0
        )

    def list_unread_links(
        self, *, user_id: int, limit: int = 500
    ) -> list[UserNotification]:
        return list(
            self._session.scalars(
                select(UserNotification)
                .where(
                    UserNotification.user_id == user_id,
                    UserNotification.is_deleted.is_(False),
                    UserNotification.is_read.is_(False),
                )
                .limit(limit)
            )
        )

    def get_subscription(
        self, *, user_id: int, event_type: str
    ) -> NotificationSubscription | None:
        return self._session.scalar(
            select(NotificationSubscription).where(
                NotificationSubscription.user_id == user_id,
                NotificationSubscription.event_type == event_type.upper(),
            )
        )

    def list_subscriptions(
        self, user_id: int
    ) -> list[NotificationSubscription]:
        return list(
            self._session.scalars(
                select(NotificationSubscription)
                .where(NotificationSubscription.user_id == user_id)
                .order_by(NotificationSubscription.event_type.asc())
            )
        )

    def upsert_subscription(
        self, row: NotificationSubscription
    ) -> NotificationSubscription:
        existing = self.get_subscription(
            user_id=int(row.user_id), event_type=row.event_type
        )
        if existing is None:
            self._session.add(row)
            self._session.commit()
            self._session.refresh(row)
            return row
        existing.enabled = row.enabled
        existing.telegram_enabled = row.telegram_enabled
        existing.web_enabled = row.web_enabled
        existing.email_enabled = row.email_enabled
        existing.quiet_time_start = row.quiet_time_start
        existing.quiet_time_end = row.quiet_time_end
        self._session.commit()
        self._session.refresh(existing)
        return existing

    def commit(self) -> None:
        self._session.commit()

    def user_link_exists(
        self, *, user_id: int, notification_id: int
    ) -> bool:
        return (
            self._session.scalar(
                select(UserNotification.user_notification_id).where(
                    and_(
                        UserNotification.user_id == user_id,
                        UserNotification.notification_id == notification_id,
                    )
                )
            )
            is not None
        )
