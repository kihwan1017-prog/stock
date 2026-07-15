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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class BrokerAccountSnapshotEntity(Base):
    """브로커 계좌 조회 결과의 최신 스냅샷."""

    __tablename__ = "broker_account_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "broker_code",
            "account_number",
            name="uq_broker_account_snapshot_account",
        ),
        {"schema": "trading"},
    )

    broker_account_snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    broker_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    account_number: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    currency_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=text("'KRW'"),
    )
    deposit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    available_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    total_purchase_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    total_evaluation_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    total_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    total_return_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        server_default=text("0"),
    )
    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    synchronized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class BrokerPositionSnapshotEntity(Base):
    """브로커 계좌 보유종목 최신 스냅샷."""

    __tablename__ = "broker_position_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "broker_code",
            "account_number",
            "exchange_code",
            "symbol",
            name="uq_broker_position_snapshot_symbol",
        ),
        {"schema": "trading"},
    )

    broker_position_snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    broker_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    account_number: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    exchange_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'KRX'"),
    )
    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
        server_default=text("0"),
    )
    available_quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
        server_default=text("0"),
    )
    average_purchase_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )
    current_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )
    purchase_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    evaluation_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    return_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        server_default=text("0"),
    )
    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    synchronized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
