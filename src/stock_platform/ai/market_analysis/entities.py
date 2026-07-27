"""STEP 11-7 — Market analysis ORM (Safe Result only)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AIMarketAnalysisEntity(Base):
    __tablename__ = "market_analysis"
    __table_args__ = (
        UniqueConstraint("analysis_key", name="uq_ai_market_analysis_key"),
        UniqueConstraint(
            "created_by",
            "idempotency_key",
            name="uq_ai_market_analysis_idempotency",
        ),
        {"schema": "ai"},
    )

    market_analysis_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    analysis_key: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(40), nullable=False)
    market_type: Mapped[str] = mapped_column(String(40), nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(40))
    timeframe: Mapped[str | None] = mapped_column(String(20))
    snapshot_key: Mapped[str] = mapped_column(String(200), nullable=False)
    snapshot_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="1"
    )
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_from: Mapped[date | None] = mapped_column(Date)
    data_to: Mapped[date | None] = mapped_column(Date)
    candle_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    indicator_version: Mapped[str | None] = mapped_column(String(40))
    execution_request_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.execution_request.execution_request_id",
            ondelete="SET NULL",
            name="fk_ai_market_analysis_exec_request",
        ),
    )
    execution_result_id: Mapped[int | None] = mapped_column(BigInteger)
    task_type: Mapped[str] = mapped_column(String(60), nullable=False)
    analysis_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="DRAFT_ANALYSIS"
    )
    execution_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="MOCK"
    )
    data_classification: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="PUBLIC"
    )
    prompt_template_id: Mapped[int | None] = mapped_column(BigInteger)
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
    output_schema_id: Mapped[int | None] = mapped_column(BigInteger)
    policy_ids: Mapped[list[Any] | None] = mapped_column(JSONB)
    provider_code: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(200))
    input_hash: Mapped[str | None] = mapped_column(String(64))
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    result_hash: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    trend_classification: Mapped[str | None] = mapped_column(String(40))
    volatility_level: Mapped[str | None] = mapped_column(String(40))
    market_regime: Mapped[str | None] = mapped_column(String(40))
    data_quality_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="UNKNOWN"
    )
    safe_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    warnings: Mapped[list[Any] | None] = mapped_column(JSONB)
    vision_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    source_missing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIMarketAnalysisIndicatorEntity(Base):
    __tablename__ = "market_analysis_indicator"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.market_analysis.market_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_mkt_ind_analysis",
        ),
        nullable=False,
    )
    indicator_code: Mapped[str] = mapped_column(String(40), nullable=False)
    indicator_version: Mapped[str] = mapped_column(String(40), nullable=False)
    timeframe: Mapped[str | None] = mapped_column(String(20))
    value_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    quality_status: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIMarketAnalysisLevelEntity(Base):
    __tablename__ = "market_analysis_level"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.market_analysis.market_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_mkt_level_analysis",
        ),
        nullable=False,
    )
    level_type: Mapped[str] = mapped_column(String(40), nullable=False)
    price: Mapped[str] = mapped_column(String(40), nullable=False)
    strength: Mapped[str | None] = mapped_column(String(40))
    evidence: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIMarketAnalysisHistoryEntity(Base):
    __tablename__ = "market_analysis_history"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.market_analysis.market_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_mkt_hist_analysis",
        ),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(500))
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    detail_sanitized: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIMarketAnalysisSnapshotRefEntity(Base):
    __tablename__ = "market_snapshot_reference"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.market_analysis.market_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_mkt_snap_analysis",
        ),
        nullable=False,
    )
    source_table: Mapped[str] = mapped_column(String(80), nullable=False)
    source_key: Mapped[str] = mapped_column(String(200), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(40))
    source_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIMarketAnalysisKrxLinkEntity(Base):
    __tablename__ = "market_analysis_krx_link"
    __table_args__ = (
        UniqueConstraint(
            "market_analysis_id", name="uq_ai_mkt_krx_link_analysis"
        ),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.market_analysis.market_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_mkt_krx_analysis",
        ),
        nullable=False,
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "market.instrument.instrument_id",
            ondelete="RESTRICT",
            name="fk_ai_mkt_krx_instrument",
        ),
        nullable=False,
    )


class AIMarketAnalysisUpbitLinkEntity(Base):
    __tablename__ = "market_analysis_upbit_link"
    __table_args__ = (
        UniqueConstraint(
            "market_analysis_id", name="uq_ai_mkt_upbit_link_analysis"
        ),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.market_analysis.market_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_mkt_upbit_analysis",
        ),
        nullable=False,
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "market.instrument.instrument_id",
            ondelete="RESTRICT",
            name="fk_ai_mkt_upbit_instrument",
        ),
        nullable=False,
    )
