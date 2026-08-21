"""Broker-agnostic strategy-owned position binding + daily PnL entities."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Identity,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


BINDING_STATUS_OPEN = "OPEN"
BINDING_STATUS_CLOSED = "CLOSED"
OWNERSHIP_STRATEGY = "STRATEGY_OWNED"
OWNERSHIP_MANUAL = "MANUAL"
OWNERSHIP_UNKNOWN = "UNKNOWN"


class StrategyPositionBindingEntity(Base):
    """자동매매 fill로 연 포지션만 소유 — 수동 보유와 분리."""

    __tablename__ = "strategy_position_binding"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "broker_code",
            "strategy_id",
            "symbol",
            "entry_order_id",
            name="uq_strategy_position_binding_entry",
        ),
        {"schema": "operation"},
    )

    binding_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    strategy_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    deployment_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text(f"'{BINDING_STATUS_OPEN}'"),
    )
    ownership_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text(f"'{OWNERSHIP_STRATEGY}'"),
    )
    entry_order_id: Mapped[int | None] = mapped_column(BigInteger)
    broker_order_id: Mapped[str | None] = mapped_column(String(80))
    owned_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default=text("0")
    )
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    fees: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class StrategyDailyPnlEntity(Base):
    """Strategy-owned 당일 PnL — Account equity baseline과 분리."""

    __tablename__ = "strategy_daily_pnl"
    __table_args__ = (
        UniqueConstraint(
            "trading_date",
            "broker_code",
            "user_broker_account_id",
            "strategy_id",
            "deployment_id",
            name="uq_strategy_daily_pnl_scope",
        ),
        {"schema": "operation"},
    )

    strategy_daily_pnl_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    strategy_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deployment_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    opening_strategy_equity: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    fees: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    current_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    current_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    loss_limit_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    entry_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    closed_trade_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    consecutive_losses: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    open_binding_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    status_code: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'SAFE'")
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
