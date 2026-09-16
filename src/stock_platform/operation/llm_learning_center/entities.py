"""ORM — LLM Learning Center user feedback + assistant history."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.operation.upbit_market_context.constants import SCHEMA_MARKET

REVIEW_STATUS_USER_REVIEWED = "USER_REVIEWED"

VALID_FEEDBACK_LABELS = frozenset(
    {
        "GOOD_DECISION",
        "BAD_DECISION",
        "EARLY_EXIT",
        "BAD_ENTRY",
        "FEE_CHURN",
        "MISSED_WINNER",
        "NEWS_EVENT",
        "MARKET_ANOMALY",
        "EXCLUDE_FROM_TRAINING",
        "OTHER",
    }
)


class LlmLearningUserCommentEntity(Base):
    """사용자 연구 코멘트 — USER_REVIEWED, 자동 GOLD 금지."""

    __tablename__ = "llm_learning_user_comment"
    __table_args__ = (
        Index("ix_llm_learning_comment_market_created", "market", "created_at"),
        {"schema": SCHEMA_MARKET},
    )

    comment_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(40))
    related_analysis_id: Mapped[int | None] = mapped_column(BigInteger)
    related_prediction_id: Mapped[int | None] = mapped_column(BigInteger)
    related_shadow_id: Mapped[int | None] = mapped_column(BigInteger)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=REVIEW_STATUS_USER_REVIEWED
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LlmLearningAssistantMessageEntity(Base):
    """Read-only assistant Q&A history — secret redaction applied before save."""

    __tablename__ = "llm_learning_assistant_message"
    __table_args__ = (
        Index("ix_llm_learning_assistant_created", "created_at"),
        {"schema": SCHEMA_MARKET},
    )

    message_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(64))
    market_scope: Mapped[str | None] = mapped_column(String(20))
    intent: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    context_refs_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(128))
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = [
    "LlmLearningUserCommentEntity",
    "LlmLearningAssistantMessageEntity",
    "REVIEW_STATUS_USER_REVIEWED",
    "VALID_FEEDBACK_LABELS",
]
