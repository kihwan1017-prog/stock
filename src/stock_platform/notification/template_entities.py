"""notification.message_template / code_translation / channel_delivery_log ORM."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class MessageTemplateEntity(Base):
    __tablename__ = "message_template"
    __table_args__ = (
        UniqueConstraint(
            "event_type",
            "channel",
            "locale",
            "version",
            name="uq_message_template_event_channel_locale_ver",
        ),
        Index(
            "ix_message_template_lookup",
            "event_type",
            "channel",
            "locale",
            "enabled",
        ),
        {"schema": "notification"},
    )

    message_template_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    locale: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'ko-KR'")
    )
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'INFO'")
    )
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audience: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'BOTH'")
    )
    title_template: Mapped[str] = mapped_column(String(400), nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    short_body_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    variables_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CodeTranslationEntity(Base):
    __tablename__ = "code_translation"
    __table_args__ = (
        UniqueConstraint(
            "code_group",
            "code",
            "locale",
            name="uq_code_translation_group_code_locale",
        ),
        {"schema": "notification"},
    )

    code_translation_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    code_group: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    locale: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'ko-KR'")
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChannelDeliveryLogEntity(Base):
    __tablename__ = "channel_delivery_log"
    __table_args__ = (
        Index("ix_channel_delivery_log_created", "created_at"),
        Index("ix_channel_delivery_log_event", "event_type", "channel"),
        {"schema": "notification"},
    )

    channel_delivery_log_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rendered_title: Mapped[str | None] = mapped_column(String(400), nullable=True)
    rendered_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locale: Mapped[str | None] = mapped_column(String(16), nullable=True)
    missing_variables_json: Mapped[Any | None] = mapped_column(
        JSONB, nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
