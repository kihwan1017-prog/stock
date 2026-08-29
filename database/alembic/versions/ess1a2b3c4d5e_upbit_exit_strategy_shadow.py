"""revision: ess1a2b3c4d5e
UPBIT Exit Strategy Forward Shadow V1 (research only).

One row per (entry_order_id, strategy_family, variant_code).
REAL exit policy unchanged. No REAL SELL from this table.

Revises: sto1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ess1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "sto1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_exit_strategy_shadow",
        sa.Column("shadow_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_broker_account_id", sa.BigInteger(), nullable=False
        ),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("deployment_id", sa.BigInteger(), nullable=True),
        sa.Column("binding_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("entry_order_id", sa.BigInteger(), nullable=False),
        sa.Column("broker_order_uuid", sa.String(80), nullable=True),
        sa.Column("entry_fill_id", sa.String(80), nullable=True),
        sa.Column(
            "entry_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "entry_price", sa.Numeric(28, 12), nullable=False
        ),
        sa.Column(
            "entry_qty", sa.Numeric(28, 12), nullable=True
        ),
        sa.Column(
            "entry_notional", sa.Numeric(20, 4), nullable=True
        ),
        sa.Column(
            "entry_fee", sa.Numeric(20, 4), nullable=True
        ),
        sa.Column(
            "strategy_family", sa.String(32), nullable=False
        ),
        sa.Column("variant_code", sa.String(40), nullable=False),
        sa.Column(
            "threshold_value", sa.Numeric(16, 8), nullable=True
        ),
        sa.Column("time_horizon_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column(
            "trigger_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "trigger_price", sa.Numeric(28, 12), nullable=True
        ),
        sa.Column(
            "peak_price", sa.Numeric(28, 12), nullable=True
        ),
        sa.Column(
            "peak_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("mfe_pct", sa.Numeric(16, 8), nullable=True),
        sa.Column("mae_pct", sa.Numeric(16, 8), nullable=True),
        sa.Column("gross_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("buy_fee", sa.Numeric(20, 4), nullable=True),
        sa.Column("sell_fee", sa.Numeric(20, 4), nullable=True),
        sa.Column("slippage", sa.Numeric(20, 4), nullable=True),
        sa.Column("net_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("hold_seconds", sa.Integer(), nullable=True),
        sa.Column("actual_exit_order_id", sa.BigInteger(), nullable=True),
        sa.Column("actual_exit_reason", sa.String(64), nullable=True),
        sa.Column(
            "actual_exit_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "actual_exit_price", sa.Numeric(28, 12), nullable=True
        ),
        sa.Column(
            "actual_net_pnl", sa.Numeric(20, 4), nullable=True
        ),
        sa.Column(
            "sample_class",
            sa.String(32),
            nullable=False,
            server_default="NATURAL_AUTO",
        ),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "state_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default="exit_strategy_shadow_v1",
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
        sa.UniqueConstraint(
            "entry_order_id",
            "strategy_family",
            "variant_code",
            name="uq_exit_strat_shadow_entry_family_variant",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_exit_strat_shadow_uba_status",
        "upbit_exit_strategy_shadow",
        ["user_broker_account_id", "status"],
        schema="operation",
    )
    op.create_index(
        "ix_exit_strat_shadow_family_status",
        "upbit_exit_strategy_shadow",
        ["strategy_family", "variant_code", "status"],
        schema="operation",
    )
    op.create_index(
        "ix_exit_strat_shadow_binding",
        "upbit_exit_strategy_shadow",
        ["binding_id"],
        schema="operation",
    )
    op.create_index(
        "ix_exit_strat_shadow_sample_class",
        "upbit_exit_strategy_shadow",
        ["sample_class", "status"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exit_strat_shadow_sample_class",
        table_name="upbit_exit_strategy_shadow",
        schema="operation",
    )
    op.drop_index(
        "ix_exit_strat_shadow_binding",
        table_name="upbit_exit_strategy_shadow",
        schema="operation",
    )
    op.drop_index(
        "ix_exit_strat_shadow_family_status",
        table_name="upbit_exit_strategy_shadow",
        schema="operation",
    )
    op.drop_index(
        "ix_exit_strat_shadow_uba_status",
        table_name="upbit_exit_strategy_shadow",
        schema="operation",
    )
    op.drop_table("upbit_exit_strategy_shadow", schema="operation")
