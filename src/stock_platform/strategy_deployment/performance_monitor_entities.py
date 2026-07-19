from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyDeploymentPerformanceEntity(Base):
    __tablename__ = "strategy_deployment_performance"
    __table_args__ = {"schema": "trading"}

    strategy_deployment_performance_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    strategy_deployment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment.strategy_deployment_id",
            ondelete="CASCADE",
            name="fk_strategy_deployment_performance_deployment",
        ),
        nullable=False,
    )
    strategy_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    total_trade_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    total_return_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
        server_default=text("0"),
    )
    maximum_drawdown_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
        server_default=text("0"),
    )
    win_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
        server_default=text("0"),
    )
    profit_factor: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8),
        nullable=True,
    )
    consecutive_losses: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    check_payload: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
