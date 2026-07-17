"""create market indicator_daily table

Revision ID: d5b1c82e4a01
Revises: c4a8e91f2b70
Create Date: 2026-07-18 08:30:00.000000

STEP36-06: 일봉 기반 기술적 지표 영속화.
overlay market.indicator (market/symbol PK) 는 사용하지 않음.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d5b1c82e4a01"
down_revision: Union[str, Sequence[str], None] = "c4a8e91f2b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "indicator_daily",
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column(
            "close_price",
            sa.Numeric(precision=20, scale=8),
            nullable=False,
        ),
        sa.Column(
            "volume",
            sa.Numeric(precision=28, scale=8),
            nullable=False,
        ),
        sa.Column("ma5", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("ma20", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("ma60", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("ema12", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("ema26", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("rsi14", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("macd", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column(
            "macd_signal",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
        sa.Column(
            "macd_histogram",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
        sa.Column(
            "bollinger_middle",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
        sa.Column(
            "bollinger_upper",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
        sa.Column(
            "bollinger_lower",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
        sa.Column("atr14", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column(
            "volume_ma20",
            sa.Numeric(precision=28, scale=8),
            nullable=True,
        ),
        sa.Column(
            "high_52w",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
            comment="52-week high (approx 252 trading days)",
        ),
        sa.Column(
            "low_52w",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
            comment="52-week low (approx 252 trading days)",
        ),
        sa.Column(
            "status_code",
            sa.String(length=20),
            server_default=sa.text("'PARTIAL'"),
            nullable=False,
            comment="READY | PARTIAL | INSUFFICIENT",
        ),
        sa.Column(
            "missing_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
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
            "status_code IN ('READY', 'PARTIAL', 'INSUFFICIENT')",
            name="ck_indicator_daily_status",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["market.instrument.instrument_id"],
            name="fk_indicator_daily_instrument_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "instrument_id",
            "trade_date",
            name="pk_indicator_daily",
        ),
        schema="market",
    )
    op.create_index(
        "ix_indicator_daily_trade_date",
        "indicator_daily",
        ["trade_date"],
        unique=False,
        schema="market",
    )
    op.create_index(
        "ix_indicator_daily_status",
        "indicator_daily",
        ["status_code"],
        unique=False,
        schema="market",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_indicator_daily_status",
        table_name="indicator_daily",
        schema="market",
    )
    op.drop_index(
        "ix_indicator_daily_trade_date",
        table_name="indicator_daily",
        schema="market",
    )
    op.drop_table("indicator_daily", schema="market")
