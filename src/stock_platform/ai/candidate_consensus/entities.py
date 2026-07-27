"""STEP 11-10 — Candidate Consensus ORM (legacy Candidate FK 없음)."""

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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AICandidateConsensusEntity(Base):
    __tablename__ = "candidate_consensus"
    __table_args__ = (
        UniqueConstraint("consensus_key", name="uq_ai_candidate_consensus_key"),
        UniqueConstraint(
            "created_by",
            "idempotency_key",
            name="uq_ai_candidate_consensus_idempotency",
        ),
        {"schema": "ai"},
    )

    consensus_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    consensus_key: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    consensus_type: Mapped[str] = mapped_column(String(20), nullable=False)
    market_type: Mapped[str] = mapped_column(String(40), nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    task_type: Mapped[str] = mapped_column(String(60), nullable=False)
    consensus_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="DRAFT"
    )
    calculation_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    execution_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="MOCK"
    )
    data_classification: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="PUBLIC_DERIVED"
    )
    evidence_bundle_hash: Mapped[str | None] = mapped_column(String(64))
    source_version_hash: Mapped[str | None] = mapped_column(String(64))
    assessment_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    included_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    excluded_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    provider_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    provider_family_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    model_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    deterministic_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="det-1.0.0"
    )
    execution_request_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.execution_request.execution_request_id",
            ondelete="SET NULL",
            name="fk_ai_candidate_consensus_exec_request",
        ),
    )
    execution_result_id: Mapped[int | None] = mapped_column(BigInteger)
    prompt_template_id: Mapped[int | None] = mapped_column(BigInteger)
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
    output_schema_id: Mapped[int | None] = mapped_column(BigInteger)
    policy_ids: Mapped[list[Any] | None] = mapped_column(JSONB)
    synthesis_provider_code: Mapped[str | None] = mapped_column(String(40))
    synthesis_model: Mapped[str | None] = mapped_column(String(200))
    weighted_analytical_score: Mapped[float | None] = mapped_column(Float)
    weighted_risk_score: Mapped[float | None] = mapped_column(Float)
    weighted_confidence: Mapped[float | None] = mapped_column(Float)
    agreement_level: Mapped[str | None] = mapped_column(String(40))
    disagreement_level: Mapped[str | None] = mapped_column(String(40))
    evidence_consistency: Mapped[str | None] = mapped_column(String(40))
    provider_diversity: Mapped[str | None] = mapped_column(String(40))
    review_decision: Mapped[str | None] = mapped_column(String(40))
    result_hash: Mapped[str | None] = mapped_column(String(64))
    safe_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    warnings: Mapped[list[Any] | None] = mapped_column(JSONB)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synthesized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class AICandidateConsensusMemberEntity(Base):
    __tablename__ = "candidate_consensus_member"
    __table_args__ = (
        UniqueConstraint(
            "candidate_consensus_id",
            "candidate_assessment_id",
            name="uq_ai_cand_consensus_member_assessment",
        ),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    candidate_consensus_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_consensus.consensus_id",
            ondelete="CASCADE",
            name="fk_ai_cand_consensus_member_consensus",
        ),
        nullable=False,
    )
    candidate_assessment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_assessment.assessment_id",
            ondelete="SET NULL",
            name="fk_ai_cand_consensus_member_assessment",
        ),
    )
    provider_code: Mapped[str | None] = mapped_column(String(40))
    provider_family: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(200))
    included: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    exclusion_reason: Mapped[str | None] = mapped_column(String(500))
    independence_status: Mapped[str | None] = mapped_column(String(40))
    base_weight: Mapped[float | None] = mapped_column(Float)
    review_weight: Mapped[float | None] = mapped_column(Float)
    scorecard_weight: Mapped[float | None] = mapped_column(Float)
    calibration_weight: Mapped[float | None] = mapped_column(Float)
    citation_weight: Mapped[float | None] = mapped_column(Float)
    data_quality_weight: Mapped[float | None] = mapped_column(Float)
    independence_weight: Mapped[float | None] = mapped_column(Float)
    final_weight: Mapped[float | None] = mapped_column(Float)
    analytical_score: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    review_decision: Mapped[str | None] = mapped_column(String(40))
    evidence_bundle_hash: Mapped[str | None] = mapped_column(String(64))
    result_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateConsensusFactorEntity(Base):
    __tablename__ = "candidate_consensus_factor"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    candidate_consensus_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_consensus.consensus_id",
            ondelete="CASCADE",
            name="fk_ai_cand_consensus_factor_consensus",
        ),
        nullable=False,
    )
    factor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    factor_code: Mapped[str] = mapped_column(String(80), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    agreement_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    disagreement_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    weighted_support: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_summary: Mapped[str | None] = mapped_column(String(1000))
    citation_reference: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateConsensusConflictEntity(Base):
    __tablename__ = "candidate_consensus_conflict"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    candidate_consensus_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_consensus.consensus_id",
            ondelete="CASCADE",
            name="fk_ai_cand_consensus_conflict_consensus",
        ),
        nullable=False,
    )
    conflict_type: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(200))
    assessment_ids: Mapped[list[Any] | None] = mapped_column(JSONB)
    description_sanitized: Mapped[str | None] = mapped_column(String(2000))
    resolution_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="UNRESOLVED"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateConsensusHistoryEntity(Base):
    __tablename__ = "candidate_consensus_history"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    candidate_consensus_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_consensus.consensus_id",
            ondelete="CASCADE",
            name="fk_ai_cand_consensus_hist_consensus",
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
