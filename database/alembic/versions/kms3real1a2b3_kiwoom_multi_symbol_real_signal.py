"""Add kiwoom_multi_symbol_real_signal lineage table.

Revision ID: kms3real1a2b3
Revises: kms2refresh1a2b
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "kms3real1a2b3"
down_revision: Union[str, Sequence[str], None] = "kms2refresh1a2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kiwoom_multi_symbol_real_signal",
        sa.Column("real_signal_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column("refresh_batch_id", sa.String(64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("signal_fingerprint", sa.String(96), nullable=False),
        sa.Column("publish_fingerprint", sa.String(96), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sma5", sa.Numeric(28, 12), nullable=True),
        sa.Column("sma20", sa.Numeric(28, 12), nullable=True),
        sa.Column("prev_sma5", sa.Numeric(28, 12), nullable=True),
        sa.Column("prev_sma20", sa.Numeric(28, 12), nullable=True),
        sa.Column("dispatch_state", sa.String(40), nullable=False),
        sa.Column(
            "dispatch_detail_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "meta_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_broker_account_id",
            "signal_fingerprint",
            name="uq_kiwoom_ms_real_sig_uba_fp",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_kiwoom_ms_real_sig_uba_created",
        "kiwoom_multi_symbol_real_signal",
        ["user_broker_account_id", "created_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_table("kiwoom_multi_symbol_real_signal", schema="operation")
