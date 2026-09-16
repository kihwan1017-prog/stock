"""사용자 AI 추천 ORM — STEP70."""

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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AiRecommendationRequest(Base):
    __tablename__ = "recommendation_request"
    __table_args__ = (
        Index(
            "ix_ai_recommendation_request_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_ai_recommendation_request_user_status",
            "user_id",
            "status",
        ),
        Index(
            "ix_ai_recommendation_request_input_hash",
            "user_id",
            "input_hash",
        ),
        {"schema": "ai"},
    )

    request_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="CASCADE",
            name="fk_ai_recommendation_request_user",
        ),
        nullable=False,
    )
    account_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    market_code: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'WATCHLIST'"),
    )
    investment_horizon: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'SHORT_TERM'"),
    )
    risk_level: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'MODERATE'"),
    )
    recommendation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'QUEUED'")
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'v1'")
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_symbols_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AiRecommendationResult(Base):
    __tablename__ = "recommendation_result"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "rank",
            name="uq_ai_recommendation_result_request_rank",
        ),
        Index(
            "ix_ai_recommendation_result_symbol",
            "market_code",
            "symbol",
        ),
        {"schema": "ai"},
    )

    result_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.recommendation_request.request_id",
            ondelete="CASCADE",
            name="fk_ai_recommendation_result_request",
        ),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    market_code: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    symbol_name: Mapped[str] = mapped_column(String(200), nullable=False)
    recommendation_action: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default=text("0")
    )
    total_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default=text("0")
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasons_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    risk_factors_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    data_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    data_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UserAiRecommendationState(Base):
    __tablename__ = "user_recommendation_state"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "request_id",
            name="uq_ai_user_recommendation_state",
        ),
        Index(
            "ix_ai_user_recommendation_state_bookmarked",
            "user_id",
            "is_bookmarked",
        ),
        {"schema": "ai"},
    )

    user_recommendation_state_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="CASCADE",
            name="fk_ai_user_recommendation_state_user",
        ),
        nullable=False,
    )
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.recommendation_request.request_id",
            ondelete="CASCADE",
            name="fk_ai_user_recommendation_state_request",
        ),
        nullable=False,
    )
    is_bookmarked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    feedback_type: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    feedback_comment: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    bookmarked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
