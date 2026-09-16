"""ORM — Entry Gate V2 shadow decisions (research only)."""

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
from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.constants import (
    MARKET,
    RULE_VERSION,
    STATUS_PENDING,
)


class UpbitEntryGateV2ShadowEntity(Base):
    """E0 vs V2 side-by-side decision log — no order/intent fields."""

    __tablename__ = "upbit_entry_gate_v2_shadow"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "symbol",
            "observed_bucket",
            "v2_candidate",
            name="uq_entry_gate_v2_uba_sym_bucket_cand",
        ),
        {"schema": "operation"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text(f"'{MARKET}'")
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # 5분 버킷 문자열 — 중복 억제 (YYYYMMDDHHMM)
    observed_bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    scanner_run_id: Mapped[str | None] = mapped_column(String(64))
    selection_id: Mapped[int | None] = mapped_column(BigInteger)

    live_e0_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    live_e0_block_reason: Mapped[str | None] = mapped_column(String(64))

    v2_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{RULE_VERSION}'")
    )
    v2_candidate: Mapped[str] = mapped_column(String(16), nullable=False)
    v2_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    v2_score: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    v2_block_reason: Mapped[str | None] = mapped_column(String(64))

    feature_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    regime: Mapped[str | None] = mapped_column(String(20))

    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    live_promotion_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    counterfactual_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_PENDING}'")
    )
    future_5m_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    future_15m_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    future_30m_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    future_60m_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    entry_reference_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
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
