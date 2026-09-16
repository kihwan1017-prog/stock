"""포트폴리오 일별 자산 스냅샷 모델 — STEP66."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class PortfolioSnapshot(Base):
    """회원·계좌별 일별 자산 스냅샷."""

    __tablename__ = "portfolio_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "snapshot_date",
            "mode_code",
            name="uq_portfolio_snapshot_account_date_mode",
        ),
        {"schema": "trading"},
    )

    snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="CASCADE",
            name="fk_portfolio_snapshot_user",
        ),
        nullable=False,
        index=True,
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id",
            ondelete="CASCADE",
            name="fk_portfolio_snapshot_account",
        ),
        nullable=False,
    )

    snapshot_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    snapshot_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )

    market_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )

    total_asset: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )

    invested_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )

    realized_profit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )

    unrealized_profit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )

    daily_profit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )

    daily_profit_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        server_default=text("0"),
    )

    total_return_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        server_default=text("0"),
    )

    position_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )

    mode_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'PAPER'"),
    )

    valuation_mode: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'mark_to_market'"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
