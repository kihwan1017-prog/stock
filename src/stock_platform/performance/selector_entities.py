from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategySelectionRunEntity(Base):
    __tablename__ = "strategy_selection_run"
    __table_args__ = {"schema": "ai"}

    strategy_selection_run_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    market_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    symbol: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    run_type: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    selected_strategy_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    selected_performance_run_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    risk_notes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    alternatives: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    candidate_payload: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    response_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
