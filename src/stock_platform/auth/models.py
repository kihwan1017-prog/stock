from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stock_platform.database.base import Base


class AuthUser(Base):
    """플랫폼 로그인 사용자 (회원 JWT)."""

    __tablename__ = "user"
    __table_args__ = {"schema": "auth"}

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    nickname: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    profile_image_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    bio: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    locale: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=text("'KO'"),
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    roles: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[\"viewer\"]'::jsonb"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None



class RefreshToken(Base):
    """Refresh 토큰 저장 (해시만 보관, 로그아웃 시 revoke)."""

    __tablename__ = "refresh_token"
    __table_args__ = {"schema": "auth"}

    refresh_token_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    session_public_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True
    )
    device_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    browser_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    operating_system: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoke_reason: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped[AuthUser] = relationship(back_populates="refresh_tokens")


class UserConnection(Base):
    """외부 서비스 연결 (Telegram 등). Secret 원문은 저장하지 않음."""

    __tablename__ = "user_connection"
    __table_args__ = {"schema": "auth"}

    connection_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'NOT_CONNECTED'")
    )
    external_ref_masked: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    external_ref_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(80), nullable=True
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
