"""UBA 일일 Equity Baseline — 등록/당일 최초 관측 평가액."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Identity,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class UbaDailyEquityBaselineEntity(Base):
    """거래일·UBA 단위 Opening Equity (Daily Loss 기준점)."""

    __tablename__ = "uba_daily_equity_baseline"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "trading_date",
            "currency_code",
            name="uq_uba_daily_equity_baseline_day",
        ),
        {"schema": "operation"},
    )

    baseline_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency_code: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'KRW'")
    )
    opening_equity: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False
    )
    source_code: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'FIRST_OBSERVED'")
    )
    # Kiwoom V1/V2 등 — NULL이면 legacy(V1 immediate cash)로 해석
    equity_policy_version: Mapped[str | None] = mapped_column(String(80))
    correlation_id: Mapped[str | None] = mapped_column(String(80))
    broker_code: Mapped[str | None] = mapped_column(String(20))
    baseline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_by: Mapped[str | None] = mapped_column(String(100))
