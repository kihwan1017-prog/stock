"""STEP33 market data foundation — overlay 참고용 (적용 금지, instrument/price_daily 사용)."""
from alembic import op
import sqlalchemy as sa

revision = "20260717_02"
down_revision = "REPLACE_WITH_CURRENT_REVISION"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "symbol",
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("listed_at", sa.Date()),
        sa.Column("delisted_at", sa.Date()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("market", "symbol", name="pk_market_symbol"),
        schema="market",
    )

    op.create_table(
        "quote",
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("change", sa.Numeric(24, 8)),
        sa.Column("change_rate", sa.Numeric(18, 8)),
        sa.Column("volume", sa.Numeric(30, 8)),
        sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("market", "symbol", name="pk_market_quote"),
        schema="market",
    )

    op.create_table(
        "trade",
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("trade_id", sa.String(100), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 8), nullable=False),
        sa.Column("side", sa.String(10)),
        sa.Column("traded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("market", "symbol", "trade_id", name="pk_market_trade"),
        schema="market",
    )
    op.create_index("ix_market_trade_symbol_time", "trade",
                    ["market", "symbol", "traded_at"], schema="market")

    op.create_table(
        "candle_day",
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("candle_date", sa.Date(), nullable=False),
        sa.Column("open_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("high_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("low_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("close_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("volume", sa.Numeric(30, 8), nullable=False),
        sa.Column("trade_amount", sa.Numeric(30, 8)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("market", "symbol", "candle_date", name="pk_market_candle_day"),
        schema="market",
    )
    op.create_index("ix_market_candle_day_symbol_date", "candle_day",
                    ["market", "symbol", "candle_date"], schema="market")

def downgrade() -> None:
    op.drop_index("ix_market_candle_day_symbol_date", table_name="candle_day", schema="market")
    op.drop_table("candle_day", schema="market")
    op.drop_index("ix_market_trade_symbol_time", table_name="trade", schema="market")
    op.drop_table("trade", schema="market")
    op.drop_table("quote", schema="market")
    op.drop_table("symbol", schema="market")
