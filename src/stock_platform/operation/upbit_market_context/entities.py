"""ORM — market/asset context snapshots + LLM research analysis.

news.* / ai.market_analysis 와 중복하지 않음.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.operation.upbit_market_context.constants import SCHEMA_MARKET


class UpbitMarketContextSnapshotEntity(Base):
    """시장 공통 snapshot — 주기 수집."""

    __tablename__ = "upbit_market_context_snapshot"
    __table_args__ = (
        Index(
            "ix_upbit_mkt_ctx_observed",
            "observed_at",
        ),
        Index(
            "ix_upbit_mkt_ctx_source_ts",
            "source",
            "source_timestamp",
        ),
        {"schema": SCHEMA_MARKET},
    )

    snapshot_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    stale_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality: Mapped[str] = mapped_column(String(32), nullable=False)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UpbitAssetContextSnapshotEntity(Base):
    """종목별 시장/체결/수익률 snapshot."""

    __tablename__ = "upbit_asset_context_snapshot"
    __table_args__ = (
        Index(
            "ix_upbit_asset_ctx_symbol_ts",
            "symbol",
            "source_timestamp",
        ),
        Index(
            "ix_upbit_asset_ctx_feature",
            "feature_key",
            "observed_at",
        ),
        {"schema": SCHEMA_MARKET},
    )

    snapshot_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    stale_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality: Mapped[str] = mapped_column(String(32), nullable=False)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UpbitAssetDescriptionCacheEntity(Base):
    """종목 설명서 장기 캐시 — scanner tick마다 재수집 금지."""

    __tablename__ = "upbit_asset_description_cache"
    __table_args__ = (
        Index("ix_upbit_asset_desc_symbol", "symbol", unique=True),
        {"schema": SCHEMA_MARKET},
    )

    cache_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    quality: Mapped[str] = mapped_column(String(32), nullable=False)
    project_summary: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str | None] = mapped_column(String(80))
    main_use_case: Mapped[str | None] = mapped_column(Text)
    token_characteristics: Mapped[str | None] = mapped_column(Text)
    known_risks: Mapped[str | None] = mapped_column(Text)
    official_links: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    stale_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UpbitLlmContextAnalysisEntity(Base):
    """LLM entry quality research row — 주문 FK 없음."""

    __tablename__ = "upbit_llm_context_analysis"
    __table_args__ = (
        Index(
            "ix_upbit_llm_ctx_symbol_asof",
            "symbol",
            "context_as_of",
        ),
        Index("ix_upbit_llm_ctx_shadow", "shadow_id"),
        {"schema": SCHEMA_MARKET},
    )

    analysis_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    shadow_id: Mapped[int | None] = mapped_column(BigInteger)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    context_as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recommendation: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    entry_quality_score: Mapped[int | None] = mapped_column(Integer)
    quality: Mapped[str] = mapped_column(String(32), nullable=False)
    lookahead_ok: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=func.true()
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=func.true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
