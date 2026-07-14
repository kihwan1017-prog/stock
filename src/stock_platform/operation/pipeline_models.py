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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class PipelineRun(Base):
    """일일 운영 파이프라인 실행 이력."""

    __tablename__ = "pipeline_run"
    __table_args__ = (
        {"schema": "operation"},
    )

    pipeline_run_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    pipeline_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    trigger_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'MANUAL'"),
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

    request_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
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


class PipelineStepRun(Base):
    """파이프라인 단계별 실행 이력."""

    __tablename__ = "pipeline_step_run"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_run_id",
            "step_name",
            name="uq_pipeline_step_run_pipeline_step",
        ),
        {"schema": "operation"},
    )

    pipeline_step_run_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    pipeline_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "operation.pipeline_run.pipeline_run_id",
            ondelete="CASCADE",
            name="fk_pipeline_step_run_pipeline",
        ),
        nullable=False,
    )

    step_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    step_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    job_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'"),
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
