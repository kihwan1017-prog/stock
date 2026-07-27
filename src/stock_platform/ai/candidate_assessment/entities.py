"""STEP 11-9 — Candidate Assessment ORM (Safe Result only, 기존 Candidate FK 없음)."""

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


class AICandidateAssessmentEntity(Base):
    __tablename__ = "candidate_assessment"
    __table_args__ = (
        UniqueConstraint("assessment_key", name="uq_ai_candidate_assessment_key"),
        UniqueConstraint(
            "created_by",
            "idempotency_key",
            name="uq_ai_candidate_assessment_idempotency",
        ),
        {"schema": "ai"},
    )

    assessment_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    assessment_key: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    assessment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    market_type: Mapped[str] = mapped_column(String(40), nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(BigInteger)
    instrument_key: Mapped[str | None] = mapped_column(String(64))
    task_type: Mapped[str] = mapped_column(String(60), nullable=False)
    assessment_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="DRAFT"
    )
    execution_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="MOCK"
    )
    data_classification: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="PUBLIC_DERIVED"
    )
    execution_request_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.execution_request.execution_request_id",
            ondelete="SET NULL",
            name="fk_ai_candidate_assessment_exec_request",
        ),
    )
    execution_result_id: Mapped[int | None] = mapped_column(BigInteger)
    prompt_template_id: Mapped[int | None] = mapped_column(BigInteger)
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
    output_schema_id: Mapped[int | None] = mapped_column(BigInteger)
    policy_ids: Mapped[list[Any] | None] = mapped_column(JSONB)
    provider_code: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(200))
    evidence_bundle_hash: Mapped[str | None] = mapped_column(String(64))
    source_version_hash: Mapped[str | None] = mapped_column(String(64))
    input_hash: Mapped[str | None] = mapped_column(String(64))
    result_hash: Mapped[str | None] = mapped_column(String(64))
    analytical_score: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    overall_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_quality: Mapped[str | None] = mapped_column(String(40))
    data_quality: Mapped[str | None] = mapped_column(String(40))
    conflict_status: Mapped[str | None] = mapped_column(String(40))
    temporal_alignment_status: Mapped[str | None] = mapped_column(String(40))
    review_decision: Mapped[str | None] = mapped_column(String(40))
    safe_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    warnings: Mapped[list[Any] | None] = mapped_column(JSONB)
    source_missing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[int | None] = mapped_column(BigInteger)
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
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


class AICandidateAssessmentEvidenceEntity(Base):
    __tablename__ = "candidate_assessment_evidence"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    candidate_assessment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_assessment.assessment_id",
            ondelete="CASCADE",
            name="fk_ai_cand_evidence_assessment",
        ),
        nullable=False,
    )
    evidence_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_analysis_type: Mapped[str] = mapped_column(String(40), nullable=False)
    document_analysis_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.document_analysis.document_analysis_id",
            ondelete="SET NULL",
            name="fk_ai_cand_evidence_doc_analysis",
        ),
    )
    market_analysis_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.market_analysis.market_analysis_id",
            ondelete="SET NULL",
            name="fk_ai_cand_evidence_mkt_analysis",
        ),
    )
    review_decision_id: Mapped[int | None] = mapped_column(BigInteger)
    source_version: Mapped[str | None] = mapped_column(String(40))
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    quality_status: Mapped[str | None] = mapped_column(String(40))
    direction: Mapped[str | None] = mapped_column(String(20))
    temporal_status: Mapped[str | None] = mapped_column(String(40))
    summary_sanitized: Mapped[str | None] = mapped_column(String(2000))
    included: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    exclusion_reason: Mapped[str | None] = mapped_column(String(500))
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateAssessmentFactorEntity(Base):
    __tablename__ = "candidate_assessment_factor"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    candidate_assessment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_assessment.assessment_id",
            ondelete="CASCADE",
            name="fk_ai_cand_factor_assessment",
        ),
        nullable=False,
    )
    factor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    factor_code: Mapped[str] = mapped_column(String(80), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    importance: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_summary: Mapped[str | None] = mapped_column(String(1000))
    citation_reference: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateAssessmentRiskEntity(Base):
    __tablename__ = "candidate_assessment_risk"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    candidate_assessment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_assessment.assessment_id",
            ondelete="CASCADE",
            name="fk_ai_cand_risk_assessment",
        ),
        nullable=False,
    )
    risk_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_summary: Mapped[str | None] = mapped_column(String(1000))
    citation_reference: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateAssessmentHistoryEntity(Base):
    __tablename__ = "candidate_assessment_history"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    candidate_assessment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_assessment.assessment_id",
            ondelete="CASCADE",
            name="fk_ai_cand_hist_assessment",
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
