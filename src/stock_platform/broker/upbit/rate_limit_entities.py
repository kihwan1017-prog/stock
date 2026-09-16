"""STEP 8-5-8 — upbit_api_rate_limit_state Entity."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class UpbitApiRateLimitStateEntity(Base):
    __tablename__ = "upbit_api_rate_limit_state"
    __table_args__ = (
        UniqueConstraint(
            "credential_scope_type",
            "user_broker_account_id",
            "endpoint_group",
            name="uq_upbit_rate_limit_scope_group",
        ),
        {"schema": "operation"},
    )

    upbit_api_rate_limit_state_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    credential_scope_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'UBA'")
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
    )
    endpoint_group: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'default'")
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'OK'")
    )
    remaining_second: Mapped[int | None] = mapped_column(Integer)
    remaining_minute: Mapped[int | None] = mapped_column(Integer)
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    blocked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_retry_after_seconds: Mapped[int | None] = mapped_column(Integer)
    consecutive_rate_limit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    last_request_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    updated_by_instance_id: Mapped[str | None] = mapped_column(String(200))
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
