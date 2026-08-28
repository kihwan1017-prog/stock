# -*- coding: utf-8 -*-
"""ORM: operation.upbit_exit_intent."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class UpbitExitIntentEntity(Base):
    """Confirmed MA exit intent — durable SoT for bounded retry (WRK-014)."""

    __tablename__ = "upbit_exit_intent"
    __table_args__ = (
        Index(
            "ix_uei_uba_status",
            "user_broker_account_id",
            "status",
        ),
        Index(
            "ix_uei_uba_symbol_status",
            "user_broker_account_id",
            "symbol",
            "status",
        ),
        Index(
            "ix_uei_next_retry_at",
            "next_retry_at",
        ),
        Index(
            "ix_uei_binding_id",
            "binding_id",
        ),
        {"schema": "operation"},
    )

    exit_intent_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    slot_id: Mapped[int | None] = mapped_column(BigInteger)
    binding_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    exit_reason: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'MA_DEAD_CROSS'")
    )
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    strategy_version: Mapped[str | None] = mapped_column(String(120))

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'CONFIRMED'")
    )

    initial_signal_id: Mapped[str | None] = mapped_column(String(100))
    initial_order_id: Mapped[int | None] = mapped_column(BigInteger)
    last_order_id: Mapped[int | None] = mapped_column(BigInteger)

    initial_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # INITIAL=0; retry orders increment 1..max_retry_count
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    max_retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )

    initial_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    remaining_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))

    last_condition_result: Mapped[str | None] = mapped_column(String(40))
    last_condition_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_block_reason: Mapped[str | None] = mapped_column(String(80))

    detail_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    event_log_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
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
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
