"""STEP 8-5-3 — Recovery Scheduler Job Entity."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
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


class BrokerRecoverySchedulerJobEntity(Base):
    """Recovery Scheduler Job 설정 (ADMIN 편집 가능)."""

    __tablename__ = "broker_recovery_scheduler_job"
    __table_args__ = {"schema": "operation"}

    scheduler_job_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    job_id: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(30), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    cron_expression: Mapped[str | None] = mapped_column(String(80))
    interval_minutes: Mapped[int | None] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'Asia/Seoul'")
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("180")
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    backoff_base_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("60")
    )
    backoff_max_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1800")
    )
    concurrency: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("2")
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_status: Mapped[str | None] = mapped_column(String(30))
    last_error_summary: Mapped[str | None] = mapped_column(Text)
    last_result_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_by: Mapped[str | None] = mapped_column(String(100))
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
