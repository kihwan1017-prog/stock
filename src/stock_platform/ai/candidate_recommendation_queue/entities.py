"""STEP 11-11 — Candidate Recommendation Queue ORM.

Safety: no strategy.candidate FK/INSERT — queue is review workflow only.
"""

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


class AICandidateRecommendationQueueEntity(Base):
    __tablename__ = "candidate_recommendation_queue"
    __table_args__ = (
        UniqueConstraint("queue_key", name="uq_ai_cand_rec_queue_key"),
        UniqueConstraint(
            "created_by",
            "idempotency_key",
            name="uq_ai_cand_rec_queue_idempotency",
        ),
        {"schema": "ai"},
    )

    queue_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    queue_key: Mapped[str] = mapped_column(String(220), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_assessment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_assessment.assessment_id",
            ondelete="RESTRICT",
            name="fk_ai_cand_rec_queue_assessment",
        ),
    )
    candidate_consensus_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_consensus.consensus_id",
            ondelete="RESTRICT",
            name="fk_ai_cand_rec_queue_consensus",
        ),
    )
    market_type: Mapped[str] = mapped_column(String(40), nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    queue_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="DRAFT"
    )
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="NORMAL"
    )
    source_result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_bundle_hash: Mapped[str | None] = mapped_column(String(64))
    source_review_decision: Mapped[str | None] = mapped_column(String(40))
    source_quality_score: Mapped[float | None] = mapped_column(Float)
    analytical_score: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    agreement_level: Mapped[str | None] = mapped_column(String(40))
    disagreement_level: Mapped[str | None] = mapped_column(String(40))
    provider_diversity: Mapped[str | None] = mapped_column(String(40))
    eligibility_version: Mapped[str | None] = mapped_column(String(40))
    eligibility_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    assigned_to: Mapped[str | None] = mapped_column(String(100))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AICandidateRecommendationReviewEntity(Base):
    __tablename__ = "candidate_recommendation_review"
    __table_args__ = (
        UniqueConstraint(
            "queue_id",
            "review_version",
            name="uq_ai_cand_rec_review_version",
        ),
        {"schema": "ai"},
    )

    review_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    queue_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_recommendation_queue.queue_id",
            ondelete="CASCADE",
            name="fk_ai_cand_rec_review_queue",
        ),
        nullable=False,
    )
    review_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    review_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="DRAFT"
    )
    reviewer_id: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    eligibility_score: Mapped[float | None] = mapped_column(Float)
    analytical_quality_score: Mapped[float | None] = mapped_column(Float)
    evidence_quality_score: Mapped[float | None] = mapped_column(Float)
    risk_awareness_score: Mapped[float | None] = mapped_column(Float)
    consistency_score: Mapped[float | None] = mapped_column(Float)
    safety_score: Mapped[float | None] = mapped_column(Float)
    overall_score: Mapped[float | None] = mapped_column(Float)
    recommendation_scope: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="CONSIDERATION_ONLY"
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amended_from_id: Mapped[int | None] = mapped_column(BigInteger)
    amendment_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AICandidateRecommendationFindingEntity(Base):
    __tablename__ = "candidate_recommendation_finding"
    __table_args__ = {"schema": "ai"}

    finding_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    review_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_recommendation_review.review_id",
            ondelete="CASCADE",
            name="fk_ai_cand_rec_finding_review",
        ),
        nullable=False,
    )
    finding_type: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(200))
    description_sanitized: Mapped[str | None] = mapped_column(String(2000))
    requires_resolution: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    resolution_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="OPEN"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateRecommendationDecisionEntity(Base):
    __tablename__ = "candidate_recommendation_decision"
    __table_args__ = (
        UniqueConstraint(
            "queue_id",
            "decision_version",
            name="uq_ai_cand_rec_decision_version",
        ),
        {"schema": "ai"},
    )

    decision_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    queue_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_recommendation_queue.queue_id",
            ondelete="RESTRICT",
            name="fk_ai_cand_rec_decision_queue",
        ),
        nullable=False,
    )
    decision_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    warning_conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decided_by: Mapped[str] = mapped_column(String(100), nullable=False)
    manager_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    override_reason: Mapped[str | None] = mapped_column(String(500))
    source_result_hash_at_decision: Mapped[str | None] = mapped_column(String(64))
    evidence_bundle_hash_at_decision: Mapped[str | None] = mapped_column(String(64))
    source_review_decision_at_decision: Mapped[str | None] = mapped_column(
        String(40)
    )
    analytical_score_at_decision: Mapped[float | None] = mapped_column(Float)
    risk_score_at_decision: Mapped[float | None] = mapped_column(Float)
    confidence_at_decision: Mapped[float | None] = mapped_column(Float)
    agreement_level_at_decision: Mapped[str | None] = mapped_column(String(40))
    disagreement_level_at_decision: Mapped[str | None] = mapped_column(String(40))
    critical_findings_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    unresolved_high_findings_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    eligibility_version: Mapped[str | None] = mapped_column(String(40))
    review_formula_version: Mapped[str | None] = mapped_column(String(40))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateRecommendationHistoryEntity(Base):
    __tablename__ = "candidate_recommendation_history"
    __table_args__ = {"schema": "ai"}

    history_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    queue_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_recommendation_queue.queue_id",
            ondelete="CASCADE",
            name="fk_ai_cand_rec_history_queue",
        ),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(500))
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateRecommendationAssignmentEntity(Base):
    __tablename__ = "candidate_recommendation_assignment"
    __table_args__ = {"schema": "ai"}

    assignment_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    queue_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_recommendation_queue.queue_id",
            ondelete="CASCADE",
            name="fk_ai_cand_rec_assignment_queue",
        ),
        nullable=False,
    )
    assignee_id: Mapped[str] = mapped_column(String(100), nullable=False)
    assignment_status: Mapped[str] = mapped_column(String(40), nullable=False)
    assigned_by: Mapped[str] = mapped_column(String(100), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
