"""STEP 11-5 — Execution Request/Run/Result/Event/Pricing ORM."""

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


class AIExecutionRequestEntity(Base):
    __tablename__ = "execution_request"
    __table_args__ = (
        UniqueConstraint(
            "requested_by",
            "idempotency_key",
            name="uq_ai_exec_idempotency",
        ),
        UniqueConstraint("request_key", name="uq_ai_exec_request_key"),
        {"schema": "ai"},
    )

    execution_request_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    task_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="DRAFT"
    )
    execution_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="MOCK"
    )
    provider_code: Mapped[str | None] = mapped_column(String(40))
    provider_configuration_id: Mapped[int | None] = mapped_column(BigInteger)
    requested_model: Mapped[str | None] = mapped_column(String(200))
    prompt_template_id: Mapped[int | None] = mapped_column(BigInteger)
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
    output_schema_id: Mapped[int | None] = mapped_column(BigInteger)
    policy_ids: Mapped[list[Any] | None] = mapped_column(JSONB)
    # 민감 입력은 기본 미저장 — 메타/해시만
    input_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    rendered_prompt_hash: Mapped[str | None] = mapped_column(String(64))
    max_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="256"
    )
    temperature: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.2"
    )
    timeout_sec: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="30"
    )
    fallback_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    retry_max: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    budget_limit: Mapped[float | None] = mapped_column(Float)
    estimated_max_cost: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="USD"
    )
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    sanitized_error: Mapped[str | None] = mapped_column(String(500))
    # 실행 시 비민감 입력 사본 (테스트/요약용) — Secret 검사 통과분만
    input_payload_sanitized: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIExecutionRunEntity(Base):
    __tablename__ = "execution_run"
    __table_args__ = (
        UniqueConstraint(
            "execution_request_id",
            "attempt_no",
            name="uq_ai_exec_run_attempt",
        ),
        {"schema": "ai"},
    )

    execution_run_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    execution_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.execution_request.execution_request_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_configuration_id: Mapped[int | None] = mapped_column(BigInteger)
    model: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="CREATED"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    actual_cost: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="USD"
    )
    cost_calculation_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="NOT_APPLICABLE"
    )
    pricing_version: Mapped[str | None] = mapped_column(String(40))
    finish_reason: Mapped[str | None] = mapped_column(String(40))
    provider_request_id: Mapped[str | None] = mapped_column(String(120))
    retry_reason: Mapped[str | None] = mapped_column(String(200))
    fallback_reason: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str | None] = mapped_column(String(80))
    sanitized_error: Mapped[str | None] = mapped_column(String(500))
    circuit_state: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIExecutionResultEntity(Base):
    __tablename__ = "execution_result"
    __table_args__ = (
        UniqueConstraint(
            "execution_request_id",
            name="uq_ai_exec_result_request",
        ),
        {"schema": "ai"},
    )

    execution_result_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    execution_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.execution_request.execution_request_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    execution_run_id: Mapped[int | None] = mapped_column(BigInteger)
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_version: Mapped[str | None] = mapped_column(String(20))
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    reasoning_summary: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[Any] | None] = mapped_column(JSONB)
    citations: Mapped[list[Any] | None] = mapped_column(JSONB)
    policy_findings: Mapped[list[Any] | None] = mapped_column(JSONB)
    data_quality: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw_response_retained: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIExecutionEventEntity(Base):
    __tablename__ = "execution_event"
    __table_args__ = {"schema": "ai"}

    execution_event_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    execution_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.execution_request.execution_request_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    execution_run_id: Mapped[int | None] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str | None] = mapped_column(String(40))
    detail_sanitized: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIProviderPricingEntity(Base):
    __tablename__ = "provider_pricing"
    __table_args__ = {"schema": "ai"}

    provider_pricing_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    model_pattern: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="USD"
    )
    input_price_per_1m_tokens: Mapped[float] = mapped_column(Float, nullable=False)
    output_price_per_1m_tokens: Mapped[float] = mapped_column(Float, nullable=False)
    pricing_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="SEED_TEST"
    )
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="OPERATOR"
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
