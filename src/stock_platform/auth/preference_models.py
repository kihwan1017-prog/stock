"""사용자 Preferences ORM — STEP72."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class UserPreference(Base):
    """회원별 UI·도메인 환경설정 (관리자 app_setting과 분리)."""

    __tablename__ = "user_preference"
    __table_args__ = {"schema": "auth"}

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="CASCADE",
            name="fk_user_preference_user",
        ),
        primary_key=True,
    )

    theme: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'system'")
    )
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'KO'")
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'Asia/Seoul'")
    )
    date_format: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'YYYY-MM-DD'")
    )
    number_format: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'1,234.56'")
    )
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'KRW'")
    )
    default_market: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'KRX'")
    )
    default_account_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    default_watchlist_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    default_dashboard: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'Dashboard'")
    )
    items_per_page: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("20")
    )

    ai_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    ai_auto_summary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    ai_recommendation_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    notification_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    telegram_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    email_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    web_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
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
