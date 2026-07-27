"""STEP 8-5-15 — 영속 Market Session Job SQLAlchemy Entities."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
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


class MarketSessionJobEntity(Base):
    """KRX Session에 종속된 영속 Job (`_DYNAMIC_JOBS` 대체, DB가 Source of Truth)."""

    __tablename__ = "market_session_job"
    __table_args__ = (
        UniqueConstraint(
            "exchange_code",
            "market_date",
            "job_type",
            "calendar_revision",
            name="uq_market_session_job_natural_key",
        ),
        Index(
            "ix_market_session_job_due",
            "status_code",
            "scheduled_for",
        ),
        Index(
            "ix_market_session_job_claim_expires",
            "claim_expires_at",
        ),
        Index(
            "ix_market_session_job_exchange_date",
            "exchange_code",
            "market_date",
        ),
        Index(
            "ix_market_session_job_revision",
            "exchange_code",
            "market_date",
            "calendar_revision",
        ),
        {"schema": "operation"},
    )

    market_session_job_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    market_date: Mapped[date] = mapped_column(Date, nullable=False)
    calendar_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # `{EXCHANGE}:{market_date}:{job_type}:rev{N}` — 전역 유일
    job_key: Mapped[str] = mapped_column(
        String(120), nullable=False, unique=True
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status_code: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'SCHEDULED'")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100"), default=100
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3"), default=3
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    claimed_by: Mapped[str | None] = mapped_column(String(200))
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    run_token: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_summary: Mapped[str | None] = mapped_column(Text)
    superseded_by_job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "operation.market_session_job.market_session_job_id",
            ondelete="SET NULL",
        ),
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    depends_on_job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "operation.market_session_job.market_session_job_id",
            ondelete="SET NULL",
        ),
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
        onupdate=func.now(),
    )

    def as_dict(self) -> dict[str, Any]:
        def _iso(v: datetime | date | None) -> str | None:
            return v.isoformat() if v else None

        return {
            "job_id": int(self.market_session_job_id),
            "exchange_code": self.exchange_code,
            "market_date": _iso(self.market_date),
            "calendar_revision": int(self.calendar_revision),
            "job_type": self.job_type,
            "job_key": self.job_key,
            "scheduled_for": _iso(self.scheduled_for),
            "status_code": self.status_code,
            "payload": self.payload,
            "priority": int(self.priority),
            "attempt_count": int(self.attempt_count),
            "max_attempts": int(self.max_attempts),
            "next_retry_at": _iso(self.next_retry_at),
            "claimed_by": self.claimed_by,
            "claimed_at": _iso(self.claimed_at),
            "claim_expires_at": _iso(self.claim_expires_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "last_error_code": self.last_error_code,
            "last_error_summary": self.last_error_summary,
            "superseded_by_job_id": self.superseded_by_job_id,
            "superseded_at": _iso(self.superseded_at),
            "depends_on_job_id": self.depends_on_job_id,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class MarketSessionJobRunEntity(Base):
    """Job 1회 실행 이력 (Claim → 실행 → 종료 감사 추적용)."""

    __tablename__ = "market_session_job_run"
    __table_args__ = (
        Index(
            "ix_market_session_job_run_job",
            "market_session_job_id",
        ),
        Index(
            "ix_market_session_job_run_created",
            "created_at",
        ),
        {"schema": "operation"},
    )

    market_session_job_run_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    market_session_job_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "operation.market_session_job.market_session_job_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    instance_id: Mapped[str | None] = mapped_column(String(200))
    run_token: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    status_code: Mapped[str] = mapped_column(String(20), nullable=False)
    result_code: Mapped[str | None] = mapped_column(String(80))
    result_summary: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_summary: Mapped[str | None] = mapped_column(Text)
    calendar_revision: Mapped[int | None] = mapped_column(Integer)
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    actual_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    lag_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def as_dict(self) -> dict[str, Any]:
        def _iso(v: datetime | None) -> str | None:
            return v.isoformat() if v else None

        return {
            "run_id": int(self.market_session_job_run_id),
            "job_id": int(self.market_session_job_id),
            "run_number": int(self.run_number),
            "instance_id": self.instance_id,
            "run_token": self.run_token,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "status_code": self.status_code,
            "result_code": self.result_code,
            "result_summary": self.result_summary,
            "error_code": self.error_code,
            "error_summary": self.error_summary,
            "calendar_revision": self.calendar_revision,
            "scheduled_for": _iso(self.scheduled_for),
            "actual_started_at": _iso(self.actual_started_at),
            "lag_seconds": self.lag_seconds,
            "created_at": _iso(self.created_at),
        }
