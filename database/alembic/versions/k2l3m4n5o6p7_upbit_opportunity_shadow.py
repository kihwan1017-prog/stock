"""UPBIT Opportunity Scanner Paper Shadow entries

Revision ID: k2l3m4n5o6p7
Revises: j4k5l6m7n8o9

가상 성과 추적 전용 — TradingOrder/Outbox와 무관.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "k2l3m4n5o6p7"
down_revision: Union[str, Sequence[str], None] = "j4k5l6m7n8o9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_opportunity_shadow",
        sa.Column(
            "shadow_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("scanner_run_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("recommendation", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("scanner_rank", sa.Integer(), nullable=True),
        sa.Column("scanner_score", sa.Float(), nullable=True),
        sa.Column("entry_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("assumed_amount_krw", sa.Numeric(20, 4), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("risk_level", sa.String(20), nullable=True),
        sa.Column("trend", sa.String(40), nullable=True),
        sa.Column("momentum", sa.String(40), nullable=True),
        sa.Column("volatility", sa.String(40), nullable=True),
        sa.Column("ma5", sa.Float(), nullable=True),
        sa.Column("ma20", sa.Float(), nullable=True),
        sa.Column("rsi14", sa.Float(), nullable=True),
        sa.Column("macd", sa.Float(), nullable=True),
        sa.Column("atr14", sa.Float(), nullable=True),
        sa.Column("volume_surge", sa.Float(), nullable=True),
        sa.Column("trade_value_24h", sa.Float(), nullable=True),
        sa.Column("market_analysis_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "live_auto_start",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("price_5m", sa.Numeric(28, 12), nullable=True),
        sa.Column("return_5m_pct", sa.Float(), nullable=True),
        sa.Column("evaluated_5m_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_15m", sa.Numeric(28, 12), nullable=True),
        sa.Column("return_15m_pct", sa.Float(), nullable=True),
        sa.Column("evaluated_15m_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_30m", sa.Numeric(28, 12), nullable=True),
        sa.Column("return_30m_pct", sa.Float(), nullable=True),
        sa.Column("evaluated_30m_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_60m", sa.Numeric(28, 12), nullable=True),
        sa.Column("return_60m_pct", sa.Float(), nullable=True),
        sa.Column("evaluated_60m_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfe_pct", sa.Float(), nullable=True),
        sa.Column("mae_pct", sa.Float(), nullable=True),
        sa.Column("sl_hit", sa.Boolean(), nullable=True),
        sa.Column("tp_hit", sa.Boolean(), nullable=True),
        sa.Column("sl_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tp_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "entry_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "evaluation_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="trading",
    )
    op.create_index(
        "ix_upbit_opp_shadow_symbol_status",
        "upbit_opportunity_shadow",
        ["symbol", "status"],
        schema="trading",
    )
    op.create_index(
        "ix_upbit_opp_shadow_detected_at",
        "upbit_opportunity_shadow",
        ["detected_at"],
        schema="trading",
    )
    op.create_index(
        "ix_upbit_opp_shadow_scanner_run",
        "upbit_opportunity_shadow",
        ["scanner_run_id"],
        schema="trading",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_upbit_opp_shadow_scanner_run",
        table_name="upbit_opportunity_shadow",
        schema="trading",
    )
    op.drop_index(
        "ix_upbit_opp_shadow_detected_at",
        table_name="upbit_opportunity_shadow",
        schema="trading",
    )
    op.drop_index(
        "ix_upbit_opp_shadow_symbol_status",
        table_name="upbit_opportunity_shadow",
        schema="trading",
    )
    op.drop_table("upbit_opportunity_shadow", schema="trading")
