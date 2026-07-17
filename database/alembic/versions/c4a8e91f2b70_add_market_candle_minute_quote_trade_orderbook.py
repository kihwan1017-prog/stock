"""add market candle_minute quote trade orderbook tables

Revision ID: c4a8e91f2b70
Revises: b8f4c2a19e03
Create Date: 2026-07-18 08:20:00.000000

STEP36-04/05:
- market.candle_minute
- market.quote_snapshot
- market.trade_tick
- market.orderbook_snapshot

기존 market.instrument / market.price_daily 재사용.
market.symbol / candle_day / quote / trade 는 생성하지 않음.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c4a8e91f2b70"
down_revision: Union[str, Sequence[str], None] = "b8f4c2a19e03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candle_minute",
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "timeframe",
            sa.SmallInteger(),
            nullable=False,
            comment="Minute timeframe (1, 3, 5, 15)",
        ),
        sa.Column(
            "candle_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Candle open time in UTC",
        ),
        sa.Column(
            "open_price",
            sa.Numeric(precision=20, scale=8),
            nullable=False,
        ),
        sa.Column(
            "high_price",
            sa.Numeric(precision=20, scale=8),
            nullable=False,
        ),
        sa.Column(
            "low_price",
            sa.Numeric(precision=20, scale=8),
            nullable=False,
        ),
        sa.Column(
            "close_price",
            sa.Numeric(precision=20, scale=8),
            nullable=False,
        ),
        sa.Column(
            "volume",
            sa.Numeric(precision=28, scale=8),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "trade_value",
            sa.Numeric(precision=28, scale=8),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "timeframe IN (1, 3, 5, 15)",
            name="ck_candle_minute_timeframe",
        ),
        sa.CheckConstraint(
            "open_price >= 0",
            name="ck_candle_minute_open_nonnegative",
        ),
        sa.CheckConstraint(
            "high_price >= 0",
            name="ck_candle_minute_high_nonnegative",
        ),
        sa.CheckConstraint(
            "low_price >= 0",
            name="ck_candle_minute_low_nonnegative",
        ),
        sa.CheckConstraint(
            "close_price >= 0",
            name="ck_candle_minute_close_nonnegative",
        ),
        sa.CheckConstraint(
            "volume >= 0",
            name="ck_candle_minute_volume_nonnegative",
        ),
        sa.CheckConstraint(
            "trade_value >= 0",
            name="ck_candle_minute_trade_value_nonnegative",
        ),
        sa.CheckConstraint(
            "high_price >= low_price",
            name="ck_candle_minute_high_not_below_low",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["market.instrument.instrument_id"],
            name="fk_candle_minute_instrument_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "instrument_id",
            "timeframe",
            "candle_at",
            name="pk_candle_minute",
        ),
        schema="market",
    )
    op.create_index(
        "ix_candle_minute_candle_at",
        "candle_minute",
        ["candle_at"],
        unique=False,
        schema="market",
    )

    op.create_table(
        "quote_snapshot",
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "trade_price",
            sa.Numeric(precision=20, scale=8),
            nullable=False,
        ),
        sa.Column(
            "bid_price",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
        sa.Column(
            "ask_price",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
        sa.Column(
            "change_price",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
        sa.Column(
            "change_rate",
            sa.Numeric(precision=18, scale=8),
            nullable=True,
        ),
        sa.Column(
            "volume",
            sa.Numeric(precision=28, scale=8),
            nullable=True,
        ),
        sa.Column(
            "quoted_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "trade_price >= 0",
            name="ck_quote_snapshot_trade_price_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["market.instrument.instrument_id"],
            name="fk_quote_snapshot_instrument_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "instrument_id",
            name="pk_quote_snapshot",
        ),
        schema="market",
    )

    op.create_table(
        "trade_tick",
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_id", sa.String(length=100), nullable=False),
        sa.Column(
            "price",
            sa.Numeric(precision=20, scale=8),
            nullable=False,
        ),
        sa.Column(
            "quantity",
            sa.Numeric(precision=28, scale=8),
            nullable=False,
        ),
        sa.Column("side", sa.String(length=10), nullable=True),
        sa.Column(
            "traded_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "price >= 0",
            name="ck_trade_tick_price_nonnegative",
        ),
        sa.CheckConstraint(
            "quantity >= 0",
            name="ck_trade_tick_quantity_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["market.instrument.instrument_id"],
            name="fk_trade_tick_instrument_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "instrument_id",
            "trade_id",
            name="pk_trade_tick",
        ),
        schema="market",
    )
    op.create_index(
        "ix_trade_tick_instrument_traded_at",
        "trade_tick",
        ["instrument_id", "traded_at"],
        unique=False,
        schema="market",
    )

    op.create_table(
        "orderbook_snapshot",
        sa.Column(
            "orderbook_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "bids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "asks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["market.instrument.instrument_id"],
            name="fk_orderbook_snapshot_instrument_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "orderbook_id",
            name="pk_orderbook_snapshot",
        ),
        sa.UniqueConstraint(
            "instrument_id",
            "captured_at",
            name="uq_orderbook_snapshot_instrument_captured",
        ),
        schema="market",
    )
    op.create_index(
        "ix_orderbook_snapshot_instrument_captured",
        "orderbook_snapshot",
        ["instrument_id", "captured_at"],
        unique=False,
        schema="market",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_orderbook_snapshot_instrument_captured",
        table_name="orderbook_snapshot",
        schema="market",
    )
    op.drop_table("orderbook_snapshot", schema="market")
    op.drop_index(
        "ix_trade_tick_instrument_traded_at",
        table_name="trade_tick",
        schema="market",
    )
    op.drop_table("trade_tick", schema="market")
    op.drop_table("quote_snapshot", schema="market")
    op.drop_index(
        "ix_candle_minute_candle_at",
        table_name="candle_minute",
        schema="market",
    )
    op.drop_table("candle_minute", schema="market")
