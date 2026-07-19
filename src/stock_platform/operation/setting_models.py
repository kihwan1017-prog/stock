from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AppSetting(Base):
    """DB 기반 플랫폼 설정 (key-value)."""

    __tablename__ = "app_setting"
    __table_args__ = {"schema": "operation"}

    setting_key: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )
    category: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    value_text: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    value_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'string'"),
    )
    is_secret: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    description: Mapped[str | None] = mapped_column(
        String(255)
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(100)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )


class AppSettingHistory(Base):
    """설정 변경 이력 (마스킹된 값 저장)."""

    __tablename__ = "app_setting_history"
    __table_args__ = {"schema": "operation"}

    history_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    setting_key: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    change_reason: Mapped[str | None] = mapped_column(
        String(255)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
