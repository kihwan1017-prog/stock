from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class PositionLimitEntity(Base):
    __tablename__ = "position_limit"
    __table_args__ = (
        UniqueConstraint(
            "broker_code",
            "account_number",
            "exchange_code",
            "symbol",
            name="uq_position_limit_scope",
        ),
        {"schema": "operation"},
    )

    position_limit_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    broker_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'KIWOOM'"),
    )
    account_number: Mapped[str] = mapped_column(
        String(30),
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
    max_quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
    )
    max_position_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )
    max_position_weight: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
