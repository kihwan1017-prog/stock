from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class RiskEventEntity(Base):
    """STEP 8-5-19 — UBA/Paper 기준 Risk Event."""

    __tablename__ = "risk_event"
    __table_args__ = (
        CheckConstraint(
            "("
            "(user_broker_account_id IS NOT NULL AND paper_account_id IS NULL "
            "AND account_scope_type = 'LIVE') OR "
            "(user_broker_account_id IS NULL AND paper_account_id IS NOT NULL "
            "AND account_scope_type = 'PAPER') OR "
            "(user_broker_account_id IS NULL AND paper_account_id IS NULL "
            "AND account_scope_type IN ('LEGACY_ORPHAN', 'SYSTEM'))"
            ")",
            name="ck_risk_event_account_scope",
        ),
        Index(
            "ix_risk_event_uba_created",
            "user_broker_account_id",
            "created_at",
        ),
        Index(
            "ix_risk_event_paper_created",
            "paper_account_id",
            "created_at",
        ),
        Index("ix_risk_event_correlation", "correlation_id"),
        {"schema": "operation"},
    )

    risk_event_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_level: Mapped[str] = mapped_column(String(20), nullable=False)
    broker_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'KIWOOM'"),
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    paper_account_id: Mapped[int | None] = mapped_column(BigInteger)
    account_scope_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'UNKNOWN'"),
    )
    masked_account_ref: Mapped[str | None] = mapped_column(String(40))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    current_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    loss_limit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
