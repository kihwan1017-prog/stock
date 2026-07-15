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
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyPerformanceRunEntity(Base):
    __tablename__ = "strategy_performance_run"
    __table_args__ = (
        UniqueConstraint(
            "strategy_code",
            "run_type",
            "market_code",
            "symbol",
            "period_start_date",
            "period_end_date",
            "parameter_hash",
            name="uq_strategy_performance_run",
        ),
        {"schema": "trading"},
    )

    strategy_performance_run_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    strategy_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    run_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'RUNNING'"),
    )
    market_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    symbol: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    period_start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    period_end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    parameter_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
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
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class StrategyPerformanceMetricEntity(Base):
    __tablename__ = "strategy_performance_metric"
    __table_args__ = (
        UniqueConstraint(
            "strategy_performance_run_id",
            name="uq_strategy_performance_metric_run",
        ),
        {"schema": "trading"},
    )

    strategy_performance_metric_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    strategy_performance_run_id: Mapped[int] = mapped_column(
        BigInteger,
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
    annualized_return_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8),
        nullable=True,
    )
    maximum_drawdown_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )
    volatility_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8),
        nullable=True,
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
    winning_trade_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    losing_trade_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    average_profit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    average_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    gross_profit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    gross_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    net_profit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
