"""SQLAlchemy entity — H2/H3 forward shadow opportunities (research only)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class UpbitH2H3ForwardShadowEntity(Base):
    __tablename__ = "upbit_h2_h3_forward_shadow"
    __table_args__ = (
        UniqueConstraint(
            "strategy",
            "symbol",
            "evaluated_at",
            "rule_hash",
            name="uq_h2h3_fs_strat_sym_at_hash",
        ),
        {"schema": "operation"},
    )

    shadow_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    strategy: Mapped[str] = mapped_column(String(8), nullable=False)
    rule_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    entry_reference_price: Mapped[Decimal] = mapped_column(
        Numeric(28, 12), nullable=False
    )
    feature_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # outcomes — null until matured (no lookahead)
    outcome_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="PENDING"
    )
    outcome_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
