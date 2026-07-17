"""STEP34 indicator table.

사용자 필수 작업:
1. `alembic heads`로 현재 최신 revision을 확인합니다.
2. 아래 `down_revision` 값을 실제 최신 revision으로 변경합니다.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260717_03"
down_revision = "20260717_02"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "indicator",
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("sma5", sa.Numeric(24, 8)),
        sa.Column("sma20", sa.Numeric(24, 8)),
        sa.Column("ema20", sa.Numeric(24, 8)),
        sa.Column("rsi14", sa.Numeric(24, 8)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("market", "symbol", "trading_date", name="pk_market_indicator"),
        schema="market",
    )
    op.create_index("ix_market_indicator_symbol_date", "indicator", ["market", "symbol", "trading_date"], schema="market")

def downgrade() -> None:
    op.drop_index("ix_market_indicator_symbol_date", table_name="indicator", schema="market")
    op.drop_table("indicator", schema="market")
