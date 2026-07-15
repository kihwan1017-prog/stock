from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyRuntimeSwitchEntity(Base):
    __tablename__ = "strategy_runtime_switch"
    __table_args__ = {"schema": "trading"}

    strategy_runtime_switch_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    previous_deployment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    target_deployment_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status_code: Mapped[str] = mapped_column(String(30), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    dry_run_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    previous_state_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    target_state_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
