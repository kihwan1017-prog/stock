"""News Intelligence Shadow decision ORM — SHADOW ONLY / REAL 비적용."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class NewsIntelligenceShadowDecisionEntity(Base):
    """뉴스/공시 informational decision provenance (REAL gate 비연동)."""

    __tablename__ = "news_intelligence_shadow_decision"
    __table_args__ = (
        UniqueConstraint(
            "market_code",
            "event_key",
            name="uq_news_intel_shadow_market_event",
        ),
        Index(
            "ix_news_intel_shadow_market_created",
            "market_code",
            "created_at",
        ),
        {"schema": "operation"},
    )

    decision_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    market_code: Mapped[str] = mapped_column(String(20), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(40))
    event_key: Mapped[str] = mapped_column(String(160), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str | None] = mapped_column(String(500))
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'INFO'")
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    effective_start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
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
