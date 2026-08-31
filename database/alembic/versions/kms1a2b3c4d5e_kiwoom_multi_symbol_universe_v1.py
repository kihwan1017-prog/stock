"""KIWOOM multi-symbol monitor + cross state tables.

Revision ID: kms1a2b3c4d5e
Revises: ggl1oauth2v1a2b3
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "kms1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "ggl1oauth2v1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kiwoom_multi_symbol_monitor",
        sa.Column("monitor_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("market", sa.String(20), nullable=False, server_default="KIWOOM"),
        sa.Column("refresh_batch_id", sa.String(64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("price", sa.Numeric(28, 12), nullable=True),
        sa.Column("volume", sa.Numeric(28, 4), nullable=True),
        sa.Column("trading_value", sa.Numeric(28, 4), nullable=True),
        sa.Column("change_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("selection_reason", sa.String(120), nullable=True),
        sa.Column("sma5", sa.Numeric(28, 12), nullable=True),
        sa.Column("sma20", sa.Numeric(28, 12), nullable=True),
        sa.Column("cross_state", sa.String(40), nullable=True),
        sa.Column("block_reason", sa.String(64), nullable=True),
        sa.Column("signal_status", sa.String(32), nullable=True),
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default="kiwoom_multi_symbol_universe_v1",
        ),
        sa.Column(
            "meta_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_broker_account_id",
            "refresh_batch_id",
            "symbol",
            name="uq_kiwoom_ms_monitor_uba_batch_symbol",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_kiwoom_ms_monitor_uba_rank",
        "kiwoom_multi_symbol_monitor",
        ["user_broker_account_id", "rank"],
        schema="operation",
    )

    op.create_table(
        "kiwoom_multi_symbol_cross_state",
        sa.Column("cross_state_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("sma5", sa.Numeric(28, 12), nullable=True),
        sa.Column("sma20", sa.Numeric(28, 12), nullable=True),
        sa.Column("prev_sma5", sa.Numeric(28, 12), nullable=True),
        sa.Column("prev_sma20", sa.Numeric(28, 12), nullable=True),
        sa.Column("cross_state", sa.String(40), nullable=False),
        sa.Column("last_cross_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "insufficient_history",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_signal_fingerprint", sa.String(96), nullable=True),
        sa.Column(
            "meta_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_broker_account_id",
            "symbol",
            name="uq_kiwoom_ms_cross_uba_symbol",
        ),
        schema="operation",
    )


def downgrade() -> None:
    op.drop_table("kiwoom_multi_symbol_cross_state", schema="operation")
    op.drop_table("kiwoom_multi_symbol_monitor", schema="operation")
