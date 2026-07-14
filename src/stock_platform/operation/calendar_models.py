from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Identity,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class TradingCalendarDay(Base):
    """거래소별 영업일·휴장일 달력."""

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

    exchange_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    calendar_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    is_trading_day: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )

    holiday_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    source_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'MANUAL'"),
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
