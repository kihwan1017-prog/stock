from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
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
