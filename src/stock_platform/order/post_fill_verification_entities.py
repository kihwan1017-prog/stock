"""STEP 8-8A — Post-Fill Verification Entity."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class PostFillVerificationEntity(Base):
    """체결 후 Position/Cash 검증 작업 (DB Source of Truth)."""

    __tablename__ = "post_fill_verification"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_post_fill_verification_idempotency",
        ),
        Index(
            "ix_post_fill_verification_due",
            "status_code",
            "next_retry_at",
        ),
        Index(
            "ix_post_fill_verification_uba",
            "user_broker_account_id",
            "status_code",
        ),
        Index(
            "ix_post_fill_verification_order",
            "order_id",
        ),
        {"schema": "trading"},
    )

    verification_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    # order:{order_id}:exec:{execution_id} — 프로세스 재시작에도 중복 방지
    idempotency_key: Mapped[str] = mapped_column(
        String(120), nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.trading_order.order_id",
            ondelete="CASCADE",
            name="fk_post_fill_verification_order",
        ),
        nullable=False,
    )
    execution_id: Mapped[int | None] = mapped_column(BigInteger)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="CASCADE",
            name="fk_post_fill_verification_uba",
        ),
        nullable=False,
    )
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    expected_position: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    expected_cash_delta: Mapped[Decimal | None] = mapped_column(
        Numeric(28, 8)
    )
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5"), default=5
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_summary: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(String(80))
    correlation_id: Mapped[str | None] = mapped_column(String(80))
    claimed_by: Mapped[str | None] = mapped_column(String(200))
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    broker_down_notified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
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
