from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class CandidateAnalysisRun(Base):
    """Ollama 후보 재평가 실행 이력 (append-only)."""

    __tablename__ = "candidate_analysis_run"
    __table_args__ = ({"schema": "ai"},)

    analysis_run_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    source_candidate_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "strategy.candidate_run.run_id",
            ondelete="CASCADE",
            name=(
                "fk_candidate_analysis_run_source_"
                "candidate_run"
            ),
        ),
        nullable=False,
    )

    exchange_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    requested_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    selected_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )

    status_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'COMPLETED'"),
    )

    prompt_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default=text("'ranker-v2'"),
    )

    context_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    used_fallback: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    error_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )

    request_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )

    parent_analysis_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_analysis_run.analysis_run_id",
            ondelete="SET NULL",
            name="fk_candidate_analysis_run_parent",
        ),
        nullable=True,
    )

    context_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class CandidateAnalysisResult(Base):
    """Ollama 후보별 평가 결과."""

    __tablename__ = "candidate_analysis_result"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id",
            "rank_no",
            name="uq_candidate_analysis_result_run_rank",
        ),
        UniqueConstraint(
            "analysis_run_id",
            "symbol",
            name="uq_candidate_analysis_result_run_symbol",
        ),
        {"schema": "ai"},
    )

    analysis_result_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    analysis_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_analysis_run.analysis_run_id",
            ondelete="CASCADE",
            name=(
                "fk_candidate_analysis_result_"
                "analysis_run"
            ),
        ),
        nullable=False,
    )

    rank_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    ai_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        nullable=False,
    )

    action_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
    )

    reasons: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    risks: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    context_used: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    rationale: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
