"""STEP 11-8 — Review / Dataset / Benchmark ORM."""

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


class AIReviewAssignmentEntity(Base):
    __tablename__ = "analysis_review_assignment"
    __table_args__ = (
        UniqueConstraint(
            "analysis_source_type",
            "source_analysis_id",
            "assigned_reviewer_id",
            name="uq_ai_review_assignment_source_reviewer",
        ),
        {"schema": "ai"},
    )

    assignment_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    analysis_source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_analysis_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_analysis_id: Mapped[int | None] = mapped_column(BigInteger)
    market_analysis_id: Mapped[int | None] = mapped_column(BigInteger)
    execution_result_id: Mapped[int | None] = mapped_column(BigInteger)
    assigned_reviewer_id: Mapped[str | None] = mapped_column(String(100))
    assigned_by: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="UNASSIGNED"
    )
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="NORMAL"
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
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


class AIAnalysisReviewEntity(Base):
    __tablename__ = "analysis_review"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "reviewer_id",
            "review_version",
            name="uq_ai_analysis_review_version",
        ),
        {"schema": "ai"},
    )

    review_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    assignment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.analysis_review_assignment.assignment_id",
            ondelete="CASCADE",
            name="fk_ai_review_assignment",
        ),
        nullable=False,
    )
    reviewer_id: Mapped[str] = mapped_column(String(100), nullable=False)
    review_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="DRAFT"
    )
    decision: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="PENDING"
    )
    overall_score: Mapped[float | None] = mapped_column(Float)
    correctness_score: Mapped[float | None] = mapped_column(Float)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    completeness_score: Mapped[float | None] = mapped_column(Float)
    citation_score: Mapped[float | None] = mapped_column(Float)
    safety_score: Mapped[float | None] = mapped_column(Float)
    clarity_score: Mapped[float | None] = mapped_column(Float)
    calibration_score: Mapped[float | None] = mapped_column(Float)
    data_quality_score: Mapped[float | None] = mapped_column(Float)
    reviewer_confidence: Mapped[float | None] = mapped_column(Float)
    findings_summary: Mapped[str | None] = mapped_column(Text)
    correction_summary: Mapped[str | None] = mapped_column(Text)
    revision_request: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    amendment_reason: Mapped[str | None] = mapped_column(String(500))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIAnalysisReviewFindingEntity(Base):
    __tablename__ = "analysis_review_finding"
    __table_args__ = {"schema": "ai"}

    finding_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    review_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.analysis_review.review_id",
            ondelete="CASCADE",
            name="fk_ai_review_finding",
        ),
        nullable=False,
    )
    finding_type: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(200))
    finding_code: Mapped[str | None] = mapped_column(String(80))
    description_sanitized: Mapped[str] = mapped_column(String(1000), nullable=False)
    suggested_correction: Mapped[str | None] = mapped_column(String(1000))
    evidence_reference: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIAnalysisReviewDecisionEntity(Base):
    __tablename__ = "analysis_review_decision"
    __table_args__ = (
        UniqueConstraint(
            "analysis_source_type",
            "source_analysis_id",
            name="uq_ai_review_decision_source",
        ),
        {"schema": "ai"},
    )

    decision_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    analysis_source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_analysis_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    decision: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="PENDING"
    )
    decision_rule: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default="AUTO"
    )
    consensus_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="INSUFFICIENT_REVIEWS"
    )
    reviewer_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    approved_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rejected_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    warning_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    average_overall_score: Mapped[float | None] = mapped_column(Float)
    critical_finding_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    decided_by: Mapped[str | None] = mapped_column(String(100))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    override_reason: Mapped[str | None] = mapped_column(String(500))
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


class AIEvaluationDatasetEntity(Base):
    __tablename__ = "evaluation_dataset"
    __table_args__ = (
        UniqueConstraint(
            "code", "dataset_version", name="uq_ai_eval_dataset_code_version"
        ),
        {"schema": "ai"},
    )

    dataset_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    task_type: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )
    dataset_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    source_policy: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default="REFERENCE_ONLY"
    )
    checksum: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIEvaluationDatasetItemEntity(Base):
    __tablename__ = "evaluation_dataset_item"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "input_reference_hash",
            name="uq_ai_eval_dataset_item_hash",
        ),
        {"schema": "ai"},
    )

    item_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.evaluation_dataset.dataset_id",
            ondelete="CASCADE",
            name="fk_ai_eval_item_dataset",
        ),
        nullable=False,
    )
    source_analysis_id: Mapped[int | None] = mapped_column(BigInteger)
    source_document_key: Mapped[str | None] = mapped_column(String(200))
    snapshot_key: Mapped[str | None] = mapped_column(String(200))
    input_reference_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expected_schema_version: Mapped[str | None] = mapped_column(String(20))
    grading_rubric: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    data_classification: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="PUBLIC"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIBenchmarkRunEntity(Base):
    __tablename__ = "benchmark_run"
    __table_args__ = {"schema": "ai"}

    benchmark_run_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    dataset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.evaluation_dataset.dataset_id",
            ondelete="RESTRICT",
            name="fk_ai_benchmark_dataset",
        ),
        nullable=False,
    )
    provider_configuration_id: Mapped[int | None] = mapped_column(BigInteger)
    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_template_id: Mapped[int | None] = mapped_column(BigInteger)
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
    output_schema_id: Mapped[int | None] = mapped_column(BigInteger)
    policy_ids: Mapped[list[Any] | None] = mapped_column(JSONB)
    execution_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="MOCK"
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="DRAFT"
    )
    item_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    completed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    blocked_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIBenchmarkResultEntity(Base):
    __tablename__ = "benchmark_result"
    __table_args__ = (
        UniqueConstraint(
            "benchmark_run_id",
            "dataset_item_id",
            name="uq_ai_benchmark_result_item",
        ),
        {"schema": "ai"},
    )

    benchmark_result_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    benchmark_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.benchmark_run.benchmark_run_id",
            ondelete="CASCADE",
            name="fk_ai_benchmark_result_run",
        ),
        nullable=False,
    )
    dataset_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    execution_request_id: Mapped[int | None] = mapped_column(BigInteger)
    score: Mapped[float | None] = mapped_column(Float)
    correctness_score: Mapped[float | None] = mapped_column(Float)
    schema_score: Mapped[float | None] = mapped_column(Float)
    citation_score: Mapped[float | None] = mapped_column(Float)
    safety_score: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    result_status: Mapped[str] = mapped_column(String(40), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    detail_sanitized: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
