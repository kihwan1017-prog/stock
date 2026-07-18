from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = {"schema": "operation"}

    audit_event_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    run_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    strategy_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    account_hash: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    order_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    client_order_id: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    symbol: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
