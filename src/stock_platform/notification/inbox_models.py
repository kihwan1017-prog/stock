"""사용자 Notification Center ORM — STEP71."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class Notification(Base):
    """공용 알림 원문 — user_id 없음."""

    __tablename__ = "notification"
    __table_args__ = (
        Index("ix_notification_created_at", "created_at"),
        Index("ix_notification_event_type", "event_type"),
        Index("ix_notification_dedupe_key", "dedupe_key"),
        {"schema": "notification"},
    )

    notification_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'INFO'")
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UserNotification(Base):
    """사용자별 알림 상태."""

    __tablename__ = "user_notification"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "notification_id",
            name="uq_user_notification_user_notification",
        ),
        Index(
            "ix_user_notification_user_read",
            "user_id",
            "is_read",
            "is_deleted",
        ),
        Index(
            "ix_user_notification_user_created",
            "user_id",
            "created_at",
        ),
        {"schema": "notification"},
    )

    user_notification_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="CASCADE",
            name="fk_user_notification_user",
        ),
        nullable=False,
    )
    notification_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "notification.notification.notification_id",
            ondelete="CASCADE",
            name="fk_user_notification_notification",
        ),
        nullable=False,
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_starred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    starred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'PENDING'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class NotificationSubscription(Base):
    """이벤트 타입별 구독 설정."""

    __tablename__ = "notification_subscription"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "event_type",
            name="uq_notification_subscription_user_event",
        ),
        {"schema": "notification"},
    )

    subscription_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="CASCADE",
            name="fk_notification_subscription_user",
        ),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    telegram_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    web_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    email_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    quiet_time_start: Mapped[str | None] = mapped_column(
        String(5), nullable=True
    )
    quiet_time_end: Mapped[str | None] = mapped_column(
        String(5), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
