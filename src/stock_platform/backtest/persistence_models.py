from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
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


class BacktestRunEntity(Base):
    """백테스트 실행 조건과 요약 결과."""

    __tablename__ = "backtest_run"
    __table_args__ = (
        {"schema": "backtest"},
    )

    backtest_run_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    strategy_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    exchange_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    initial_capital: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    final_equity: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    total_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    total_return_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
    )

    maximum_drawdown_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
    )

    trade_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    win_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    loss_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    win_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
    )

    average_trade_return_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
    )

    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'SUCCESS'"),
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


class BacktestTradeEntity(Base):
    """백테스트 거래 상세."""

    __tablename__ = "backtest_trade"
    __table_args__ = (
        UniqueConstraint(
            "backtest_run_id",
            "trade_no",
            name="uq_backtest_trade_run_no",
        ),
        {"schema": "backtest"},
    )

    backtest_trade_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    backtest_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "backtest.backtest_run.backtest_run_id",
            ondelete="CASCADE",
            name="fk_backtest_trade_run",
        ),
        nullable=False,
    )

    trade_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    entry_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    exit_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
    )

    entry_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    exit_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    gross_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    fee_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    net_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    return_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
    )

    entry_reason: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    exit_reason: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )


class BacktestEquityEntity(Base):
    """백테스트 일자별 자산 곡선."""

    __tablename__ = "backtest_equity"
    __table_args__ = (
        UniqueConstraint(
            "backtest_run_id",
            "trade_date",
            name="uq_backtest_equity_run_date",
        ),
        {"schema": "backtest"},
    )

    backtest_equity_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    backtest_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "backtest.backtest_run.backtest_run_id",
            ondelete="CASCADE",
            name="fk_backtest_equity_run",
        ),
        nullable=False,
    )

    trade_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    equity_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )
