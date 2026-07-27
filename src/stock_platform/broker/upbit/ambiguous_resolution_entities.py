"""STEP 8-5-14 — Upbit Ambiguous Resolver Scheduler 실행 이력 Entity."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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


class UpbitAmbiguousResolutionRunEntity(Base):
    """Resolver Scheduler 배치 1회 실행 결과 (영속 이력).

    Remote 조회만 수행하는 배치의 감사 추적용. 주문 재제출은 절대 하지 않는다.
    """

    __tablename__ = "upbit_ambiguous_resolution_run"
    __table_args__ = {"schema": "operation"}

    upbit_ambiguous_resolution_run_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    # SCHEDULER | ADMIN_MANUAL
    trigger_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'SCHEDULER'")
    )
    requested_by: Mapped[str | None] = mapped_column(String(150))
    instance_id: Mapped[str | None] = mapped_column(String(200))
    # RUNNING | SUCCEEDED | PARTIAL | FAILED
    status_code: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'RUNNING'")
    )
    due_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    claimed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    found_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    not_found_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    manual_review_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    conflict_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    lock_busy_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    credential_blocked_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    rate_limited_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    error_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    result_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": int(self.upbit_ambiguous_resolution_run_id),
            "trigger_type": self.trigger_type,
            "requested_by": self.requested_by,
            "instance_id": self.instance_id,
            "status_code": self.status_code,
            "due_count": int(self.due_count),
            "claimed_count": int(self.claimed_count),
            "found_count": int(self.found_count),
            "not_found_count": int(self.not_found_count),
            "manual_review_count": int(self.manual_review_count),
            "conflict_count": int(self.conflict_count),
            "lock_busy_count": int(self.lock_busy_count),
            "credential_blocked_count": int(self.credential_blocked_count),
            "rate_limited_count": int(self.rate_limited_count),
            "error_count": int(self.error_count),
            "result_summary": self.result_summary,
            "error_message": self.error_message,
            "started_at": (
                self.started_at.isoformat() if self.started_at else None
            ),
            "finished_at": (
                self.finished_at.isoformat() if self.finished_at else None
            ),
            "duration_ms": self.duration_ms,
        }
