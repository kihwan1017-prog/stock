from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class TradingExecution(Base):
    __tablename__ = "execution"
    __table_args__ = (
        UniqueConstraint(
            "broker_code",
            "broker_execution_id",
            name=(
                "uq_execution_broker_execution"
            ),
        ),
        Index(
            "ix_execution_order_id",
            "order_id",
        ),
        Index(
            "ix_execution_executed_at",
            "executed_at",
        ),
        {"schema": "trading"},
    )

    execution_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.trading_order.order_id"
        ),
        nullable=False,
    )
    broker_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="KIWOOM",
    )
    broker_order_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    broker_execution_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    side_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    execution_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    execution_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    raw_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
