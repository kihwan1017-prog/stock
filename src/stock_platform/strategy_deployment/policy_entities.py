from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyApprovalRunEntity(Base):
    __tablename__ = "strategy_approval_run"
    __table_args__ = {"schema": "trading"}

    strategy_approval_run_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    strategy_selection_run_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    strategy_performance_run_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    strategy_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    market_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    symbol: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    decision_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    automatic_approval: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("false"),
    )
    requested_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    decided_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    policy_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    check_payload: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    deployment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
