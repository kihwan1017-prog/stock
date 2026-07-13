from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.database.mixins import TimestampMixin


class Instrument(TimestampMixin, Base):
    """주식·가상자산 등 거래 가능한 자산의 마스터 정보."""

    __tablename__ = "instrument"

    __table_args__ = (
        UniqueConstraint(
            "exchange_code",
            "symbol",
            name="uq_instrument_exchange_symbol",
        ),
        CheckConstraint(
            "asset_type IN ('STOCK', 'CRYPTO', 'ETF', 'INDEX')",
            name="asset_type",
        ),
        {"schema": "market"},
    )

    instrument_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    asset_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Asset type (STOCK, CRYPTO, ETF, INDEX)",
    )

    exchange_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Exchange code (KRX, UPBIT, etc.)",
    )

    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="Trading symbol",
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Instrument name",
    )

    currency_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=text("'KRW'"),
        comment="Trading currency",
    )

    listed_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="Listing date",
    )

    delisted_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="Delisting date",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        comment="Whether the instrument is active",
    )

    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Additional metadata from external APIs",
    )


class PriceDaily(Base):
    """주식·가상자산의 일봉 시세."""

    __tablename__ = "price_daily"

    __table_args__ = (
        CheckConstraint(
            "open_price >= 0",
            name="open_price_nonnegative",
        ),
        CheckConstraint(
            "high_price >= 0",
            name="high_price_nonnegative",
        ),
        CheckConstraint(
            "low_price >= 0",
            name="low_price_nonnegative",
        ),
        CheckConstraint(
            "close_price >= 0",
            name="close_price_nonnegative",
        ),
        CheckConstraint(
            "volume >= 0",
            name="volume_nonnegative",
        ),
        CheckConstraint(
            "trade_value >= 0",
            name="trade_value_nonnegative",
        ),
        CheckConstraint(
            "high_price >= low_price",
            name="high_not_below_low",
        ),
        Index(
            "ix_price_daily_trade_date",
            "trade_date",
        ),
        {"schema": "market"},
    )

    instrument_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "market.instrument.instrument_id",
            ondelete="CASCADE",
            name="fk_price_daily_instrument_id_instrument",
        ),
        primary_key=True,
    )

    trade_date: Mapped[date] = mapped_column(
        Date,
        primary_key=True,
        comment="Trading date",
    )

    open_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        comment="Open price",
    )

    high_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        comment="High price",
    )

    low_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        comment="Low price",
    )

    close_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        comment="Close price",
    )

    volume: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
        server_default=text("0"),
        comment="Trading volume",
    )

    trade_value: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
        server_default=text("0"),
        comment="Trading value",
    )

    change_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
        comment="Change rate in percent",
    )

    source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="Data source (KIWOOM, UPBIT, etc.)",
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
