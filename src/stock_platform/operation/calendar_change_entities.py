"""STEP 8-5-11 — Calendar Change Request / History Entities."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
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


class TradingCalendarChangeRequest(Base):
    """KRX Calendar 변경 요청 — 직접 UPDATE 대체."""

    __tablename__ = "trading_calendar_change_request"
    __table_args__ = {"schema": "operation"}

    change_request_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    market_date: Mapped[date] = mapped_column(Date, nullable=False)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    current_values: Mapped[dict | None] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(200))
    source_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    emergency: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'DRAFT'"),
    )
    conflict_message: Mapped[str | None] = mapped_column(String(500))
    expected_revision: Mapped[int | None] = mapped_column(Integer)
    applied_revision: Mapped[int | None] = mapped_column(Integer)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    review_comment: Mapped[str | None] = mapped_column(String(500))
    applied_by: Mapped[str | None] = mapped_column(String(100))
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    rejected_reason: Mapped[str | None] = mapped_column(String(500))
    supersedes_request_id: Mapped[int | None] = mapped_column(BigInteger)
    rollback_of_request_id: Mapped[int | None] = mapped_column(BigInteger)
    scheduler_recompute_status: Mapped[str | None] = mapped_column(String(40))
    scheduler_recompute_error: Mapped[str | None] = mapped_column(String(500))
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


class TradingCalendarDayHistory(Base):
    """Calendar Day 적용 이력 — 삭제 금지."""

    __tablename__ = "trading_calendar_day_history"
    __table_args__ = (
        UniqueConstraint(
            "exchange_code",
            "calendar_date",
            "revision",
            name="uq_calendar_day_history_rev",
        ),
        {"schema": "operation"},
    )

    history_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    change_request_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "operation.trading_calendar_change_request.change_request_id",
            ondelete="SET NULL",
            name="fk_calendar_history_request",
        ),
    )
    before_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    after_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    source_type: Mapped[str | None] = mapped_column(String(40))
    emergency: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    applied_by: Mapped[str] = mapped_column(String(100), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    rollback_target: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
