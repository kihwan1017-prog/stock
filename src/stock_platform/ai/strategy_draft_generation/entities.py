"""STEP 12-2-2 — Strategy Draft Generation Run/Attempt ORM.

Run = 생성 요청 1건(사용자가 버튼을 누른 단위). Attempt = 그 Run 안에서
실제로 이뤄진 Provider 호출 1회(재시도 시 새 Attempt). 이 분리는
`ai.execution_request`(STEP11-5)의 request/run 분리와 동일한 패턴이다
(그쪽은 범용 실행 인프라, 이쪽은 Strategy Draft 전용 Provenance/재검증
컬럼을 갖는 별도 도메인).

Hard Delete 금지 — FK는 History/Provenance 보존 원칙에 따라 기본
RESTRICT를 사용한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyDraftGenerationRunEntity(Base):
    __tablename__ = "strategy_draft_generation_run"
    __table_args__ = (
        UniqueConstraint(
            "strategy_request_id",
            "idempotency_key",
            name="uq_ai_sdg_run_idempotency",
        ),
        Index(
            "ux_ai_sdg_run_active",
            "strategy_request_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'RUNNING')"),
        ),
        Index("ix_ai_sdg_run_request", "strategy_request_id"),
        Index("ix_ai_sdg_run_status", "status"),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLED','TIMED_OUT')",
            name="ck_ai_sdg_run_status",
        ),
        CheckConstraint("retry_number >= 0", name="ck_ai_sdg_run_retry_nonneg"),
        {"schema": "ai"},
    )

    generation_run_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    strategy_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_request.strategy_request_id",
            ondelete="RESTRICT",
            name="fk_ai_sdg_run_request",
        ),
        nullable=False,
    )
    candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_lifecycle.candidate_id",
            ondelete="RESTRICT",
            name="fk_ai_sdg_run_candidate",
        ),
        nullable=False,
    )
    draft_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_draft.draft_id",
            ondelete="RESTRICT",
            name="fk_ai_sdg_run_draft",
        ),
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING"
    )

    # 생성 직전(짧은 트랜잭션) 재검증 시점 Provenance
    candidate_lifecycle_status_at_request: Mapped[str] = mapped_column(
        String(40), nullable=False
    )
    candidate_fingerprint_at_request: Mapped[str | None] = mapped_column(String(64))
    strategy_request_fingerprint_at_review: Mapped[str | None] = mapped_column(
        String(64)
    )
    candidate_provenance_fingerprint: Mapped[str | None] = mapped_column(String(64))
    candidate_provenance_schema_version: Mapped[str | None] = mapped_column(
        String(20)
    )

    prompt_template_id: Mapped[int | None] = mapped_column(BigInteger)
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    model_parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    retry_of_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_draft_generation_run.generation_run_id",
            ondelete="RESTRICT",
            name="fk_ai_sdg_run_retry_of",
        ),
    )
    retry_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))

    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    executed_by: Mapped[str] = mapped_column(String(100), nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StrategyDraftGenerationAttemptEntity(Base):
    __tablename__ = "strategy_draft_generation_attempt"
    __table_args__ = (
        UniqueConstraint(
            "generation_run_id", "attempt_no", name="uq_ai_sdg_attempt_no"
        ),
        CheckConstraint("attempt_no >= 1", name="ck_ai_sdg_attempt_no_positive"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_sdg_attempt_input_tokens_nonneg",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_sdg_attempt_output_tokens_nonneg",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_ai_sdg_attempt_total_tokens_nonneg",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_ai_sdg_attempt_latency_nonneg",
        ),
        {"schema": "ai"},
    )

    generation_attempt_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    generation_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_draft_generation_run.generation_run_id",
            ondelete="RESTRICT",
            name="fk_ai_sdg_attempt_run",
        ),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    system_prompt_hash: Mapped[str | None] = mapped_column(String(64))
    user_prompt_hash: Mapped[str | None] = mapped_column(String(64))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    request_payload_hash: Mapped[str | None] = mapped_column(String(64))
    response_hash: Mapped[str | None] = mapped_column(String(64))
    # 원문 미저장 정책(execution_result.raw_response_retained=False 기본값과
    # 동일 컨벤션) — 검증을 통과한 구조화 결과(safe payload)만 저장한다.
    structured_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float | None] = mapped_column(Float)

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
