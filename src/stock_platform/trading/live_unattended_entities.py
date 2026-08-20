"""24H Unattended LIVE authorization lease entity."""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class LiveUnattendedAuthorizationEntity(Base):
    __tablename__ = "live_unattended_authorization"
    __table_args__ = {"schema": "operation"}

    live_unattended_authorization_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    entry_authorized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    protective_exit_authorized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    authorized_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    renewal_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3600")
    )
    renewal_margin_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("600")
    )
    arm_lease_ttl_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3600")
    )
    activation_renew_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("8")
    )
    max_authorization_horizon_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("168")
    )
    last_renewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_renewal_actor: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    last_renewal_detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    approved_by: Mapped[str] = mapped_column(String(100), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_phrase_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    source_activation_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True
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
    )
