from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Identity,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class WalkForwardWindowMetricEntity(Base):
    __tablename__ = "walk_forward_window_metric"
    __table_args__ = (
        UniqueConstraint(
            "strategy_performance_run_id",
            "window_no",
            name="uq_walk_forward_window_metric",
        ),
        {"schema": "trading"},
    )

    walk_forward_window_metric_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    strategy_performance_run_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    window_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    train_start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    train_end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    test_start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    test_end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    initial_capital: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )
    final_capital: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )
    total_return_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )
    maximum_drawdown_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )
    sharpe_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8),
        nullable=True,
    )
    sortino_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8),
        nullable=True,
    )
    win_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )
    profit_factor: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8),
        nullable=True,
    )
    total_trade_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    net_profit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    parameter_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    result_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
