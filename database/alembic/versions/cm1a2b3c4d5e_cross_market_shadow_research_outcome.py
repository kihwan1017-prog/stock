"""Cross-market shadow research — UPBIT 4h/24h outcomes + KIWOOM K0 table.

Revision ID: cm1a2b3c4d5e
Revises: ue1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cm1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "ue1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # UPBIT entry shadow — extended forward horizons
    op.add_column(
        "upbit_entry_signal_shadow",
        sa.Column("future_240m_return_pct", sa.Numeric(20, 8), nullable=True),
        schema="operation",
    )
    op.add_column(
        "upbit_entry_signal_shadow",
        sa.Column("future_1440m_return_pct", sa.Numeric(20, 8), nullable=True),
        schema="operation",
    )

    # KIWOOM Golden Cross research-only shadow (K0 baseline)
    op.create_table(
        "kiwoom_entry_signal_shadow",
        sa.Column("shadow_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False, server_default="KIWOOM"),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("research_opportunity_id", sa.String(96), nullable=False),
        sa.Column("variant", sa.String(8), nullable=False, server_default="K0"),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default="kiwoom_entry_signal_shadow_v1",
        ),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("entry_event", sa.String(32), nullable=False),
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
        sa.Column("future_240m_return_pct", sa.Numeric(20, 8), nullable=True),
        sa.Column("future_1440m_return_pct", sa.Numeric(20, 8), nullable=True),
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
            "data_quality_status",
            sa.String(32),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column(
            "included_in_research_metrics",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("quarantine_reason", sa.String(80), nullable=True),
        sa.Column("quality_window_id", sa.BigInteger(), nullable=True),
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
            "research_opportunity_id",
            "variant",
            "source",
            name="uq_kiwoom_entry_shadow_uba_opp_var_src",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_kiwoom_entry_shadow_uba_obs",
        "kiwoom_entry_signal_shadow",
        ["user_broker_account_id", "observed_at"],
        schema="operation",
    )
    op.create_index(
        "ix_kiwoom_entry_shadow_status",
        "kiwoom_entry_signal_shadow",
        ["outcome_status"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_kiwoom_entry_shadow_status",
        table_name="kiwoom_entry_signal_shadow",
        schema="operation",
    )
    op.drop_index(
        "ix_kiwoom_entry_shadow_uba_obs",
        table_name="kiwoom_entry_signal_shadow",
        schema="operation",
    )
    op.drop_table("kiwoom_entry_signal_shadow", schema="operation")
    op.drop_column(
        "upbit_entry_signal_shadow",
        "future_1440m_return_pct",
        schema="operation",
    )
    op.drop_column(
        "upbit_entry_signal_shadow",
        "future_240m_return_pct",
        schema="operation",
    )
