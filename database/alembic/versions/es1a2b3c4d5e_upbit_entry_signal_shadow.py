"""Upbit entry signal shadow — research only, REAL policy unchanged.

Revision ID: es1a2b3c4d5e
Revises: x4y5z6a7b8c9
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "es1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "x4y5z6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_entry_signal_shadow",
        sa.Column("shadow_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False, server_default="UPBIT"),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("selection_id", sa.BigInteger(), nullable=True),
        sa.Column("candidate_ref", sa.String(64), nullable=True),
        sa.Column("variant", sa.String(8), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default="entry_signal_shadow_v1",
        ),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("baseline_decision", sa.String(20), nullable=False),
        sa.Column("baseline_block_reason", sa.String(64), nullable=True),
        sa.Column("shadow_decision", sa.String(20), nullable=False),
        sa.Column("shadow_block_reason", sa.String(64), nullable=True),
        sa.Column(
            "indicator_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("entry_reference_price", sa.Numeric(28, 12), nullable=True),
        sa.Column("future_5m_return_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("future_15m_return_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("future_30m_return_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("future_60m_return_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("mfe_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("mae_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("net_return_15m_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("fee_rt_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column(
            "outcome_status",
            sa.String(40),
            nullable=False,
            server_default="PENDING",
        ),
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
            "selection_id",
            "variant",
            "source",
            name="uq_entry_signal_shadow_uba_sel_var_src",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_entry_signal_shadow_uba_obs",
        "upbit_entry_signal_shadow",
        ["user_broker_account_id", "observed_at"],
        schema="operation",
    )
    op.create_index(
        "ix_entry_signal_shadow_status",
        "upbit_entry_signal_shadow",
        ["outcome_status"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_entry_signal_shadow_status",
        table_name="upbit_entry_signal_shadow",
        schema="operation",
    )
    op.drop_index(
        "ix_entry_signal_shadow_uba_obs",
        table_name="upbit_entry_signal_shadow",
        schema="operation",
    )
    op.drop_table("upbit_entry_signal_shadow", schema="operation")
