from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyDeploymentEntity(Base):
    __tablename__ = "strategy_deployment"
    __table_args__ = (
        UniqueConstraint(
            "market_code",
            "symbol",
            "mode_code",
            "status_code",
            name="uq_strategy_deployment_active_scope",
        ),
        {"schema": "trading"},
    )

    strategy_deployment_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    strategy_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    strategy_performance_run_id: Mapped[int] = mapped_column(
        BigInteger,
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
    mode_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'PAPER'"),
    )
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    parameter_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    requested_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    replaced_by_deployment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class StrategyDeploymentHistoryEntity(Base):
    __tablename__ = "strategy_deployment_history"
    __table_args__ = {"schema": "trading"}

    strategy_deployment_history_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    strategy_deployment_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    action_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    detail_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
