from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Identity, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class MarketDataBackfillCheckpoint(Base):
    """누락 일봉 보정 진행 상태 — 재시작 후 이어서 수행."""

    __tablename__ = "market_data_backfill_checkpoint"
    __table_args__ = ({"schema": "operation"},)

    checkpoint_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    data_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    repair_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="PENDING",
    )
    gap_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
