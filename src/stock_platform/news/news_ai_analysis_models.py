"""STEP N4 — news.news_ai_analysis ORM."""

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


class NewsAIAnalysis(Base):
    """UPBIT News AI Analysis — INFORMATIONAL ONLY (주문/Gate 비연동)."""

    __tablename__ = "news_ai_analysis"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "analysis_version",
            "model_name",
            "prompt_version",
            "input_hash",
            name="uq_news_ai_analysis_idempotency",
        ),
        Index(
            "ix_news_ai_analysis_status_created",
            "status",
            "created_at",
        ),
        {"schema": "news"},
    )

    analysis_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "news.news_article.article_id",
            ondelete="CASCADE",
            name="fk_news_ai_analysis_article",
        ),
        nullable=False,
    )
    analysis_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    news_impact_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    time_horizon: Mapped[str | None] = mapped_column(String(30), nullable=True)
    market_scope: Mapped[str | None] = mapped_column(String(30), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    news_ai_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    affected_symbols: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    risk_flags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    trusted_symbols_input: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
