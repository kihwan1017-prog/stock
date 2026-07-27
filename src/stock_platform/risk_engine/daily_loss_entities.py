"""STEP 8-5-19 — LIVE/Paper Daily Loss 영속 테이블 (Method A)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Identity,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AccountDailyLossEntity(Base):
    __tablename__ = "account_daily_loss"
    __table_args__ = (
        CheckConstraint(
            "("
            "(user_broker_account_id IS NOT NULL AND paper_account_id IS NULL "
            "AND account_scope_type = 'LIVE') OR "
            "(user_broker_account_id IS NULL AND paper_account_id IS NOT NULL "
            "AND account_scope_type = 'PAPER')"
            ")",
            name="ck_account_daily_loss_exactly_one_scope",
        ),
        Index(
            "uq_account_daily_loss_uba",
            "user_broker_account_id",
            "trading_date",
            "currency_code",
            "market_code",
            unique=True,
            postgresql_where=text("user_broker_account_id IS NOT NULL"),
        ),
        Index(
            "uq_account_daily_loss_paper",
            "paper_account_id",
            "trading_date",
            "currency_code",
            "market_code",
            unique=True,
            postgresql_where=text("paper_account_id IS NOT NULL"),
        ),
        {"schema": "operation"},
    )

    account_daily_loss_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    account_scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    paper_account_id: Mapped[int | None] = mapped_column(BigInteger)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=text("'KRW'"),
    )
    market_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'KRX'"),
    )
    realized_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    unrealized_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    combined_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    current_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    loss_limit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'SAFE'"),
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
