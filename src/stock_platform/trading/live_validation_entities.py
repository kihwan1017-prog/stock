"""STEP 8-9 — Upbit 소액 LIVE Validation Run Entity."""

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


class LiveValidationRunEntity(Base):
    __tablename__ = "live_validation_run"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_live_validation_run_idempotency",
        ),
        UniqueConstraint(
            "run_id",
            name="uq_live_validation_run_run_id",
        ),
        Index(
            "ix_live_validation_run_uba_status",
            "user_broker_account_id",
            "status_code",
        ),
        Index(
            "ix_live_validation_run_preflight",
            "preflight_id",
        ),
        {"schema": "trading"},
    )

    live_validation_run_pk: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    preflight_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="CASCADE",
            name="fk_live_validation_run_uba",
        ),
        nullable=False,
    )
    broker_code: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'UPBIT'")
    )
    market: Mapped[str] = mapped_column(String(30), nullable=False)
    side_code: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    limit_price: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    execute_live: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status_code: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'CREATED'")
    )
    order_id: Mapped[int | None] = mapped_column(BigInteger)
    order_status: Mapped[str | None] = mapped_column(String(40))
    preflight_result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    post_fill_verification_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
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
    # STEP 8-9A — 내부/Broker 상태 분리
    internal_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'CREATED'"),
    )
    broker_order_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'NOT_SUBMITTED'"),
    )
    broker_identifier: Mapped[str | None] = mapped_column(String(120))
    broker_order_uuid: Mapped[str | None] = mapped_column(String(80))
    submission_attempt_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    last_broker_query_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    status_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    next_track_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    track_attempt_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    watch_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    filled_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    avg_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    filled_amount: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    manual_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    claim_owner: Mapped[str | None] = mapped_column(String(80))
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
