from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class LiveTradingTransitionEntity(Base):
    __tablename__ = "live_trading_transition"
    __table_args__ = {"schema": "operation"}

    live_trading_transition_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    environment_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'KIWOOM'"),
    )
    requested_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    approval_phrase_hash: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    max_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )
    max_daily_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )
    validation_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    disable_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
