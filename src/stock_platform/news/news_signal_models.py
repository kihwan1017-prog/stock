"""STEP N5 — news.news_signal ORM (INFORMATIONAL ONLY)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class NewsSignal(Base):
    """UPBIT News Signal — OBSERVATION ONLY (Scanner/Gate/Trading 비연동)."""

    __tablename__ = "news_signal"
    __table_args__ = (
        UniqueConstraint(
            "news_ai_analysis_id",
            "symbol",
            "signal_version",
            name="uq_news_signal_idempotency",
        ),
        Index("ix_news_signal_status_created", "signal_status", "created_at"),
        Index("ix_news_signal_symbol_signal_at", "symbol", "signal_at"),
        {"schema": "news"},
    )

    signal_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "news.news_article.article_id",
            ondelete="CASCADE",
            name="fk_news_signal_article",
        ),
        nullable=False,
    )
    news_ai_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "news.news_ai_analysis.analysis_id",
            ondelete="CASCADE",
            name="fk_news_signal_analysis",
        ),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_version: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_policy_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    strength: Mapped[str] = mapped_column(String(20), nullable=False)
    reliability: Mapped[str] = mapped_column(String(20), nullable=False)
    signal_status: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    news_impact_level: Mapped[str] = mapped_column(String(20), nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(30), nullable=False)
    news_ai_confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False
    )
    mapping_confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False
    )
    risk_flags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    reason_codes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signal_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
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
