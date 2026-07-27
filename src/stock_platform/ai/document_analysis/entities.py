"""STEP 11-6 — Document analysis ORM (Safe Result only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AIDocumentAnalysisEntity(Base):
    __tablename__ = "document_analysis"
    __table_args__ = (
        UniqueConstraint(
            "analysis_key",
            name="uq_ai_document_analysis_key",
        ),
        UniqueConstraint(
            "created_by",
            "idempotency_key",
            name="uq_ai_document_analysis_idempotency",
        ),
        {"schema": "ai"},
    )

    document_analysis_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    analysis_key: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    document_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_document_key: Mapped[str] = mapped_column(String(120), nullable=False)
    source_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="1"
    )
    market_type: Mapped[str | None] = mapped_column(String(40))
    symbol: Mapped[str | None] = mapped_column(String(30))
    company_id: Mapped[str | None] = mapped_column(String(20))
    execution_request_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.execution_request.execution_request_id",
            ondelete="SET NULL",
            name="fk_ai_doc_analysis_exec_request",
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
        String(20), nullable=False, server_default="PUBLIC"
    )
    prompt_template_id: Mapped[int | None] = mapped_column(BigInteger)
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
    output_schema_id: Mapped[int | None] = mapped_column(BigInteger)
    policy_ids: Mapped[list[Any] | None] = mapped_column(JSONB)
    provider_code: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(200))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    normalized_content_hash: Mapped[str | None] = mapped_column(String(64))
    result_hash: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    importance_score: Mapped[float | None] = mapped_column(Float)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(40))
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    safe_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    warnings: Mapped[list[Any] | None] = mapped_column(JSONB)
    unresolved_entities: Mapped[list[Any] | None] = mapped_column(JSONB)
    unmatched_symbols: Mapped[list[Any] | None] = mapped_column(JSONB)
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


class AIDocumentAnalysisTopicEntity(Base):
    __tablename__ = "document_analysis_topic"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.document_analysis.document_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_doc_topic_analysis",
        ),
        nullable=False,
    )
    topic_code: Mapped[str] = mapped_column(String(80), nullable=False)
    topic_name: Mapped[str] = mapped_column(String(200), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    evidence_summary: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIDocumentAnalysisEntityRow(Base):
    __tablename__ = "document_analysis_entity"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.document_analysis.document_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_doc_entity_analysis",
        ),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_code: Mapped[str | None] = mapped_column(String(40))
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    relevance: Mapped[float | None] = mapped_column(Float)
    sentiment: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIDocumentAnalysisCitationEntity(Base):
    __tablename__ = "document_analysis_citation"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.document_analysis.document_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_doc_citation_analysis",
        ),
        nullable=False,
    )
    citation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    excerpt_hash: Mapped[str | None] = mapped_column(String(64))
    position_start: Mapped[int | None] = mapped_column(Integer)
    position_end: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIDocumentAnalysisHistoryEntity(Base):
    __tablename__ = "document_analysis_history"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.document_analysis.document_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_doc_history_analysis",
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


class AIDocumentAnalysisNewsLinkEntity(Base):
    """뉴스 소스 명시적 FK (polymorphic id 보강)."""

    __tablename__ = "document_analysis_news_link"
    __table_args__ = (
        UniqueConstraint(
            "document_analysis_id",
            name="uq_ai_doc_news_link_analysis",
        ),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.document_analysis.document_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_doc_news_link_analysis",
        ),
        nullable=False,
    )
    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "news.news_article.article_id",
            ondelete="RESTRICT",
            name="fk_ai_doc_news_link_article",
        ),
        nullable=False,
    )


class AIDocumentAnalysisDisclosureLinkEntity(Base):
    """공시 소스 명시적 FK."""

    __tablename__ = "document_analysis_disclosure_link"
    __table_args__ = (
        UniqueConstraint(
            "document_analysis_id",
            name="uq_ai_doc_disclosure_link_analysis",
        ),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_analysis_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.document_analysis.document_analysis_id",
            ondelete="CASCADE",
            name="fk_ai_doc_disclosure_link_analysis",
        ),
        nullable=False,
    )
    disclosure_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "disclosure.dart_disclosure.disclosure_id",
            ondelete="RESTRICT",
            name="fk_ai_doc_disclosure_link_disclosure",
        ),
        nullable=False,
    )
