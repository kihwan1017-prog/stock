"""Upbit Entry Gate V2 shadow table — research only.

Revision ID: egv2a1b2c3d4
Revises: uobs1v11a2b3c4
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "egv2a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "uobs1v11a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS operation")
    op.create_table(
        "upbit_entry_gate_v2_shadow",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False, server_default="UPBIT"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_bucket", sa.String(16), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("scanner_run_id", sa.String(64), nullable=True),
        sa.Column("selection_id", sa.BigInteger(), nullable=True),
        sa.Column("live_e0_decision", sa.String(20), nullable=False),
        sa.Column("live_e0_block_reason", sa.String(64), nullable=True),
        sa.Column(
            "v2_version",
            sa.String(64),
            nullable=False,
            server_default="entry_gate_v2_shadow_v1",
        ),
        sa.Column("v2_candidate", sa.String(16), nullable=False),
        sa.Column("v2_decision", sa.String(20), nullable=False),
        sa.Column("v2_score", sa.Numeric(12, 6), nullable=True),
        sa.Column("v2_block_reason", sa.String(64), nullable=True),
        sa.Column(
            "feature_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("regime", sa.String(20), nullable=True),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "live_promotion_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "counterfactual_status",
            sa.String(40),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("future_5m_return_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("future_15m_return_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("future_30m_return_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("future_60m_return_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("entry_reference_price", sa.Numeric(28, 12), nullable=True),
        sa.Column(
            "outcome_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "user_broker_account_id",
            "symbol",
            "observed_bucket",
            "v2_candidate",
            name="uq_entry_gate_v2_uba_sym_bucket_cand",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_entry_gate_v2_uba_obs",
        "upbit_entry_gate_v2_shadow",
        ["user_broker_account_id", "observed_at"],
        schema="operation",
    )
    op.create_index(
        "ix_entry_gate_v2_e0_v2",
        "upbit_entry_gate_v2_shadow",
        ["live_e0_decision", "v2_decision"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_entry_gate_v2_e0_v2",
        table_name="upbit_entry_gate_v2_shadow",
        schema="operation",
    )
    op.drop_index(
        "ix_entry_gate_v2_uba_obs",
        table_name="upbit_entry_gate_v2_shadow",
        schema="operation",
    )
    op.drop_table("upbit_entry_gate_v2_shadow", schema="operation")
