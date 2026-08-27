"""ORM — Upbit entry signal forward shadow (research only)."""

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
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.constants import (
    MARKET,
    RULE_VERSION,
    STATUS_PENDING,
)


class UpbitEntrySignalShadowEntity(Base):
    """Forward/replay observation per (selection, variant) — REAL mutation 0."""

    __tablename__ = "upbit_entry_signal_shadow"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "selection_id",
            "variant",
            "source",
            name="uq_entry_signal_shadow_uba_sel_var_src",
        ),
        {"schema": "operation"},
    )

    shadow_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    market: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text(f"'{MARKET}'")
    )
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    selection_id: Mapped[int | None] = mapped_column(BigInteger)
    candidate_ref: Mapped[str | None] = mapped_column(String(64))
    variant: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{RULE_VERSION}'")
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    baseline_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    baseline_block_reason: Mapped[str | None] = mapped_column(String(64))
    shadow_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    shadow_block_reason: Mapped[str | None] = mapped_column(String(64))
    indicator_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    entry_reference_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    future_5m_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    future_15m_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    future_30m_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    future_60m_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    mfe_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    mae_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    net_return_15m_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    fee_rt_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    outcome_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_PENDING}'")
    )
    outcome_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
