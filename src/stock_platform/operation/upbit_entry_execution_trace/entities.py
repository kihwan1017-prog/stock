"""ORM — append-only UPBIT entry execution trace events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class UpbitEntryExecutionTraceEntity(Base):
    """Append-only decision trace — REAL trading state mutation 금지."""

    __tablename__ = "upbit_entry_execution_trace"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_ueet_idempotency_key",
        ),
        Index("ix_ueet_execution_trace_id", "execution_trace_id"),
        Index("ix_ueet_uba_selection_created", "user_broker_account_id", "selection_id", "created_at"),
        Index("ix_ueet_symbol_created", "symbol", "created_at"),
        Index("ix_ueet_order_id", "order_id"),
        {"schema": "operation"},
    )

    trace_row_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    execution_trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    selection_id: Mapped[int | None] = mapped_column(BigInteger)
    candidate_id: Mapped[int | None] = mapped_column(BigInteger)
    waiting_id: Mapped[int | None] = mapped_column(BigInteger)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    lifecycle_kind: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'INITIAL'")
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80))
    reason_detail: Mapped[str | None] = mapped_column(Text)
    signal_id: Mapped[str | None] = mapped_column(String(100))
    order_id: Mapped[int | None] = mapped_column(BigInteger)
    outbox_id: Mapped[int | None] = mapped_column(BigInteger)
    related_object_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    detail_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
