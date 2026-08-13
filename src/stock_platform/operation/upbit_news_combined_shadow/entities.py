"""STEP N6 — operation.upbit_news_combined_shadow ORM (EXPERIMENT ONLY)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class UpbitNewsCombinedShadowEntity(Base):
    """Technical + News Combined Shadow A/B — CONTROL Shadow와 분리."""

    __tablename__ = "upbit_news_combined_shadow"
    __table_args__ = (
        UniqueConstraint(
            "scanner_run_id",
            "symbol",
            "experiment_version",
            name="uq_news_combined_shadow_idempotency",
        ),
        Index(
            "ix_news_combined_shadow_status_created",
            "evaluation_status",
            "created_at",
        ),
        {"schema": "operation"},
    )

    experiment_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    experiment_version: Mapped[str] = mapped_column(String(64), nullable=False)
    combined_policy_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    scanner_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    control_scanner_rank: Mapped[int | None] = mapped_column(Integer)
    control_scanner_score: Mapped[float | None] = mapped_column(Float)
    control_market_ai_recommendation: Mapped[str | None] = mapped_column(
        String(20)
    )
    control_market_ai_confidence: Mapped[float | None] = mapped_column(Float)
    control_market_ai_risk: Mapped[str | None] = mapped_column(String(20))
    control_analysis_id: Mapped[int | None] = mapped_column(BigInteger)
    control_shadow_id: Mapped[int | None] = mapped_column(BigInteger)

    technical_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    news_context_status: Mapped[str] = mapped_column(String(32), nullable=False)
    eligible_news_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    news_signal_ids: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    news_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    experimental_news_component: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0")
    )
    news_component_normalized: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0")
    )
    experimental_combined_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0")
    )
    experimental_decision: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    counterfactual_rank: Mapped[int | None] = mapped_column(Integer)
    rank_delta: Mapped[int | None] = mapped_column(Integer)

    entry_price: Mapped[Decimal] = mapped_column(
        Numeric(28, 12), nullable=False
    )
    evaluation_status: Mapped[str] = mapped_column(String(20), nullable=False)

    return_5m_pct: Mapped[float | None] = mapped_column(Float)
    return_15m_pct: Mapped[float | None] = mapped_column(Float)
    return_30m_pct: Mapped[float | None] = mapped_column(Float)
    return_60m_pct: Mapped[float | None] = mapped_column(Float)
    mfe_pct: Mapped[float | None] = mapped_column(Float)
    mae_pct: Mapped[float | None] = mapped_column(Float)
    evaluation_detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
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
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
