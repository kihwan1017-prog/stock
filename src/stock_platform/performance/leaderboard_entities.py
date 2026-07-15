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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyLeaderboardSnapshotEntity(Base):
    __tablename__ = "strategy_leaderboard_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date",
            "run_type",
            "market_code",
            "symbol",
            "minimum_trade_count",
            name="uq_strategy_leaderboard_snapshot_scope",
        ),
        {"schema": "trading"},
    )

    strategy_leaderboard_snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    snapshot_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    run_type: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    market_code: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    symbol: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    minimum_trade_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    strategy_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    ranking_payload: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class StrategyLeaderboardEntryEntity(Base):
    __tablename__ = "strategy_leaderboard_entry"
    __table_args__ = (
        UniqueConstraint(
            "strategy_leaderboard_snapshot_id",
            "rank_no",
            name="uq_strategy_leaderboard_entry_rank",
        ),
        UniqueConstraint(
            "strategy_leaderboard_snapshot_id",
            "strategy_performance_run_id",
            name="uq_strategy_leaderboard_entry_run",
        ),
        {"schema": "trading"},
    )

    strategy_leaderboard_entry_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    strategy_leaderboard_snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    rank_no: Mapped[int] = mapped_column(
        Integer,
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
    run_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    score: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
