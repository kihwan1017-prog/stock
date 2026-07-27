"""STEP 8-5-4 — Broker Recovery Conflict Entity."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
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


class BrokerRecoveryConflictEntity(Base):
    __tablename__ = "broker_recovery_conflict"
    __table_args__ = {"schema": "operation"}

    broker_recovery_conflict_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    broker_recovery_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "operation.broker_recovery_run.broker_recovery_run_id",
            ondelete="SET NULL",
            name="fk_recovery_conflict_run",
        ),
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="SET NULL",
            name="fk_recovery_conflict_uba",
        ),
    )
    paper_account_id: Mapped[int | None] = mapped_column(BigInteger)
    broker_code: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'UPBIT'")
    )
    conflict_type: Mapped[str] = mapped_column(String(60), nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    external_order_id_masked: Mapped[str | None] = mapped_column(String(40))
    market_code: Mapped[str | None] = mapped_column(String(40))
    side_code: Mapped[str | None] = mapped_column(String(10))
    order_type_code: Mapped[str | None] = mapped_column(String(30))
    external_status: Mapped[str | None] = mapped_column(String(40))
    requested_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    executed_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    remaining_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    order_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    average_execution_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8)
    )
    paid_fee: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    external_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    review_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'PENDING_REVIEW'"),
    )
    risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'HIGH'")
    )
    resolution_type: Mapped[str | None] = mapped_column(String(60))
    resolved_by: Mapped[str | None] = mapped_column(String(100))
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    linked_internal_order_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.trading_order.order_id",
            ondelete="SET NULL",
            name="fk_recovery_conflict_order",
        ),
    )
    last_remote_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    remote_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    pause_reason: Mapped[str | None] = mapped_column(String(80))
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
