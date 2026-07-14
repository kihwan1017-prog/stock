from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class PaperAccount(Base):
    """모의투자 계좌."""

    __tablename__ = "paper_account"
    __table_args__ = (
        UniqueConstraint(
            "account_name",
            name="uq_paper_account_account_name",
        ),
        {"schema": "trading"},
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    account_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    currency_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=text("'KRW'"),
    )

    initial_cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    available_cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    realized_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
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


class PaperPosition(Base):
    """모의 계좌의 종목별 보유 포지션."""

    __tablename__ = "paper_position"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "exchange_code",
            "symbol",
            name="uq_paper_position_account_symbol",
        ),
        {"schema": "trading"},
    )

    position_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id",
            ondelete="CASCADE",
            name="fk_paper_position_account",
        ),
        nullable=False,
    )

    exchange_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
        server_default=text("0"),
    )

    average_entry_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )

    highest_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )

    realized_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
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


class PaperTrade(Base):
    """모의 체결로 생성된 매매 원장."""

    __tablename__ = "paper_trade"
    __table_args__ = (
        {"schema": "trading"},
    )

    trade_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id",
            ondelete="CASCADE",
            name="fk_paper_trade_account",
        ),
        nullable=False,
    )

    order_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_order.order_id",
            ondelete="SET NULL",
            name="fk_paper_trade_order",
        ),
        nullable=True,
    )

    exchange_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    side: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
    )

    fill_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    trade_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    realized_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )

    traded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
