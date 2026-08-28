"""AI/Cursor 개발 작업 이력 — trading control plane과 분리."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AiDevelopmentWorkHistory(Base):
    __tablename__ = "ai_development_work_history"
    __table_args__ = {"schema": "operation"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    work_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    parent_work_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    project_code: Mapped[str] = mapped_column(String(64), nullable=False)

    work_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)

    request_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    executor: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    command_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    safety_constraints_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_verdict: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    base_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)

    changed_files_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tests_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    deployment_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    safety_result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    remaining_issues_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)

    command_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
