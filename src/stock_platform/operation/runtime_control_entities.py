"""STEP 10-2 — 운영 Runtime Control State (DB 영속)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base

COMPONENT_TRADING_SCHEDULER = "TRADING_SCHEDULER"
SCOPE_GLOBAL = "GLOBAL"


class RuntimeControlStateEntity(Base):
    """컴포넌트별 desired/actual 메타 — Scheduler 등."""

    __tablename__ = "runtime_control_state"
    __table_args__ = (
        UniqueConstraint(
            "component",
            "scope_type",
            "scope_id",
            name="uq_runtime_control_state_scope",
        ),
        Index("ix_runtime_control_state_component", "component"),
        {"schema": "operation"},
    )

    control_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=SCOPE_GLOBAL
    )
    scope_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    desired_state: Mapped[str] = mapped_column(String(32), nullable=False)
    last_actual_state: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    requested_by: Mapped[str | None] = mapped_column(String(128))
    requested_reason: Mapped[str | None] = mapped_column(Text())
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    blocked_reason: Mapped[str | None] = mapped_column(String(256))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    startup_restore_attempted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    startup_restore_result: Mapped[str | None] = mapped_column(String(64))
    process_instance_id: Mapped[str | None] = mapped_column(String(128))
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
