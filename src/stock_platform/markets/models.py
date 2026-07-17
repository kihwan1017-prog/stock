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
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.database.mixins import TimestampMixin


ALLOWED_MINUTE_TIMEFRAMES = (1, 3, 5, 15)


class Instrument(TimestampMixin, Base):
    """주식·가상자산 등 거래 가능한 상품의 마스터 정보."""

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


class CandleMinute(Base):
    """분봉 시세 (1/3/5/15분). UTC candle_at 기준."""

    __tablename__ = "candle_minute"

    __table_args__ = (
        CheckConstraint(
            "timeframe IN (1, 3, 5, 15)",
            name="ck_candle_minute_timeframe",
        ),
        CheckConstraint(
            "open_price >= 0",
            name="ck_candle_minute_open_nonnegative",
        ),
        CheckConstraint(
            "high_price >= 0",
            name="ck_candle_minute_high_nonnegative",
        ),
        CheckConstraint(
            "low_price >= 0",
            name="ck_candle_minute_low_nonnegative",
        ),
        CheckConstraint(
            "close_price >= 0",
            name="ck_candle_minute_close_nonnegative",
        ),
        CheckConstraint(
            "volume >= 0",
            name="ck_candle_minute_volume_nonnegative",
        ),
        CheckConstraint(
            "trade_value >= 0",
            name="ck_candle_minute_trade_value_nonnegative",
        ),
        CheckConstraint(
            "high_price >= low_price",
            name="ck_candle_minute_high_not_below_low",
        ),
        Index("ix_candle_minute_candle_at", "candle_at"),
        {"schema": "market"},
    )

    instrument_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "market.instrument.instrument_id",
            ondelete="CASCADE",
            name="fk_candle_minute_instrument_id",
        ),
        primary_key=True,
    )

    timeframe: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
        comment="Minute timeframe (1, 3, 5, 15)",
    )

    candle_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        comment="Candle open time in UTC",
    )

    open_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
        server_default=text("0"),
    )
    trade_value: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
        server_default=text("0"),
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
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


class QuoteSnapshot(Base):
    """종목별 최신 호가/현재가 스냅샷."""

    __tablename__ = "quote_snapshot"

    __table_args__ = (
        CheckConstraint(
            "trade_price >= 0",
            name="ck_quote_snapshot_trade_price_nonnegative",
        ),
        {"schema": "market"},
    )

    instrument_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "market.instrument.instrument_id",
            ondelete="CASCADE",
            name="fk_quote_snapshot_instrument_id",
        ),
        primary_key=True,
    )
    trade_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    bid_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    ask_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    change_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    change_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TradeTick(Base):
    """체결 틱."""

    __tablename__ = "trade_tick"

    __table_args__ = (
        CheckConstraint(
            "price >= 0",
            name="ck_trade_tick_price_nonnegative",
        ),
        CheckConstraint(
            "quantity >= 0",
            name="ck_trade_tick_quantity_nonnegative",
        ),
        Index(
            "ix_trade_tick_instrument_traded_at",
            "instrument_id",
            "traded_at",
        ),
        {"schema": "market"},
    )

    instrument_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "market.instrument.instrument_id",
            ondelete="CASCADE",
            name="fk_trade_tick_instrument_id",
        ),
        primary_key=True,
    )
    trade_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    side: Mapped[str | None] = mapped_column(String(10), nullable=True)
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class OrderbookSnapshot(Base):
    """호가창 스냅샷."""

    __tablename__ = "orderbook_snapshot"

    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "captured_at",
            name="uq_orderbook_snapshot_instrument_captured",
        ),
        Index(
            "ix_orderbook_snapshot_instrument_captured",
            "instrument_id",
            "captured_at",
        ),
        {"schema": "market"},
    )

    orderbook_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "market.instrument.instrument_id",
            ondelete="CASCADE",
            name="fk_orderbook_snapshot_instrument_id",
        ),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    bids: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    asks: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class IndicatorDaily(Base):
    """일봉 기반 기술적 지표 스냅샷."""

    __tablename__ = "indicator_daily"

    __table_args__ = (
        CheckConstraint(
            "status_code IN ('READY', 'PARTIAL', 'INSUFFICIENT')",
            name="ck_indicator_daily_status",
        ),
        Index("ix_indicator_daily_trade_date", "trade_date"),
        Index("ix_indicator_daily_status", "status_code"),
        {"schema": "market"},
    )

    instrument_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "market.instrument.instrument_id",
            ondelete="CASCADE",
            name="fk_indicator_daily_instrument_id",
        ),
        primary_key=True,
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    ma5: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    ma20: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    ma60: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    ema12: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    ema26: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    rsi14: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    macd: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    macd_signal: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    macd_histogram: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    bollinger_middle: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    bollinger_upper: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    bollinger_lower: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    atr14: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    volume_ma20: Mapped[Decimal | None] = mapped_column(
        Numeric(28, 8), nullable=True
    )
    high_52w: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    low_52w: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    status_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'PARTIAL'"),
    )
    missing_fields: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
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
