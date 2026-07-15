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
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class RiskEventEntity(Base):
    __tablename__ = "risk_event"
    __table_args__ = {"schema": "operation"}

    risk_event_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    event_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
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
    current_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    loss_limit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    detail_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
