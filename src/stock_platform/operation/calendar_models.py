from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Identity,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class TradingCalendarDay(Base):
    """거래소별 영업일·휴장일 달력 (STEP 8-5-7 확장)."""

    __tablename__ = "trading_calendar_day"
    __table_args__ = (
        UniqueConstraint(
            "exchange_code",
            "calendar_date",
            name="uq_trading_calendar_exchange_date",
        ),
        {"schema": "operation"},
    )

    calendar_day_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_trading_day: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    holiday_name: Mapped[str | None] = mapped_column(String(200))
    source_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'MANUAL'"),
    )
    session_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'REGULAR'"),
    )
    preopen_at: Mapped[time | None] = mapped_column(Time)
    regular_open_at: Mapped[time | None] = mapped_column(Time)
    regular_close_at: Mapped[time | None] = mapped_column(Time)
    after_hours_close_at: Mapped[time | None] = mapped_column(Time)
    timezone: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'Asia/Seoul'"),
    )
    closure_reason: Mapped[str | None] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'MANUAL'"),
    )
    source_reference: Mapped[str | None] = mapped_column(String(200))
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    verified_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'UNVERIFIED'"),
    )
    verified_by: Mapped[str | None] = mapped_column(String(100))
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # STEP 8-5-11 — 낙관적 잠금 / 변경 추적
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1"), default=1
    )
    active_change_request_id: Mapped[int | None] = mapped_column(BigInteger)
    last_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
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


class TradingCalendarSyncRun(Base):
    """Calendar Sync 실행 이력."""

    __tablename__ = "trading_calendar_sync_run"
    __table_args__ = {"schema": "operation"}

    sync_run_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    status_code: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'RUNNING'")
    )
    trigger_type: Mapped[str | None] = mapped_column(String(30))
    requested_by: Mapped[str | None] = mapped_column(String(100))
    from_date: Mapped[date | None] = mapped_column(Date)
    to_date: Mapped[date | None] = mapped_column(Date)
    upserted_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    conflict_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    result_payload: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
