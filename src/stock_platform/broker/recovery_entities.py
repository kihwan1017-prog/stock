from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class BrokerRecoveryRunEntity(Base):
    __tablename__ = "broker_recovery_run"
    __table_args__ = {"schema": "operation"}

    broker_recovery_run_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'RUNNING'"),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    result_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    # STEP 8-4
    trigger_type: Mapped[str | None] = mapped_column(String(30))
    broker_code: Mapped[str | None] = mapped_column(String(30))
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    paper_account_id: Mapped[int | None] = mapped_column(BigInteger)
    user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger
    )
    requested_by: Mapped[str | None] = mapped_column(String(100))
    open_orders_checked: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    orders_updated: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    fills_created: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    balances_updated: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    positions_updated: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    conflicts_found: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    # STEP 8-5-6 — Distributed Lock fencing metadata
    fencing_token: Mapped[int | None] = mapped_column(BigInteger)
    lock_scope_key: Mapped[str | None] = mapped_column(String(80))
    owner_instance_id: Mapped[str | None] = mapped_column(String(200))
    lease_id: Mapped[str | None] = mapped_column(String(64))


class BrokerRecoveryStepEntity(Base):
    __tablename__ = "broker_recovery_step"
    __table_args__ = {"schema": "operation"}

    broker_recovery_step_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    broker_recovery_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "operation.broker_recovery_run.broker_recovery_run_id",
            ondelete="CASCADE",
            name="fk_broker_recovery_step_run",
        ),
        nullable=False,
    )
    component_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
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
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
