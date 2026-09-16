"""Exit Optimization Shadow Lab V3 — Alembic DDL.

Revision ID: eosv3lab1a2b3
Revises: eorlabv1a2b3
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "eosv3lab1a2b3"
down_revision: Union[str, Sequence[str], None] = "eorlabv1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_exit_optimization_shadow_v3_policy",
        sa.Column("policy_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "policy_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("policy_version", name="uq_eosv3_policy_version"),
        schema="operation",
    )

    op.create_table(
        "upbit_exit_optimization_shadow_v3_enrollment",
        sa.Column("enrollment_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False, server_default="UPBIT"),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("binding_id", sa.BigInteger(), nullable=False),
        sa.Column("entry_order_id", sa.BigInteger(), nullable=True),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("entry_quantity", sa.Numeric(28, 12), nullable=True),
        sa.Column("entry_fee", sa.Numeric(20, 4), nullable=True),
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default="exit_optimization_shadow_v3",
        ),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("real_exit_reason", sa.String(64), nullable=True),
        sa.Column("real_exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("real_exit_price", sa.Numeric(28, 12), nullable=True),
        sa.Column("real_gross_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("real_fees", sa.Numeric(20, 4), nullable=True),
        sa.Column("real_net_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("real_holding_seconds", sa.Numeric(18, 3), nullable=True),
        sa.Column(
            "path_state_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("real_closed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("binding_id", name="uq_eosv3_enrollment_binding"),
        schema="operation",
    )
    op.create_index(
        "ix_eosv3_enrollment_uba",
        "upbit_exit_optimization_shadow_v3_enrollment",
        ["user_broker_account_id"],
        schema="operation",
    )
    op.create_index(
        "ix_eosv3_enrollment_status",
        "upbit_exit_optimization_shadow_v3_enrollment",
        ["status"],
        schema="operation",
    )

    op.create_table(
        "upbit_exit_optimization_shadow_v3_variant",
        sa.Column("variant_row_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("enrollment_id", sa.BigInteger(), nullable=False),
        sa.Column("binding_id", sa.BigInteger(), nullable=False),
        sa.Column("variant_id", sa.String(8), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="ACTIVE"),
        sa.Column("shadow_exit_reason", sa.String(64), nullable=True),
        sa.Column("shadow_exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shadow_exit_price", sa.Numeric(28, 12), nullable=True),
        sa.Column("shadow_gross_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("shadow_estimated_exit_fee", sa.Numeric(20, 4), nullable=True),
        sa.Column("shadow_estimated_net_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("holding_seconds", sa.Numeric(18, 3), nullable=True),
        sa.Column("mfe_pct", sa.Numeric(16, 8), nullable=True),
        sa.Column("mae_pct", sa.Numeric(16, 8), nullable=True),
        sa.Column("peak_profit_pct", sa.Numeric(16, 8), nullable=True),
        sa.Column("current_profit_pct", sa.Numeric(16, 8), nullable=True),
        sa.Column("short_ma", sa.Numeric(28, 12), nullable=True),
        sa.Column("long_ma", sa.Numeric(28, 12), nullable=True),
        sa.Column("ma_relation", sa.String(32), nullable=True),
        sa.Column("estimated_entry_fee", sa.Numeric(20, 4), nullable=True),
        sa.Column("estimated_round_trip_fee", sa.Numeric(20, 4), nullable=True),
        sa.Column("trigger_reason", sa.String(64), nullable=True),
        sa.Column("defer_reason", sa.String(128), nullable=True),
        sa.Column(
            "deferred_trailing_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("baseline_terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shadow_terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "continuation_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "meta_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
            "binding_id",
            "variant_id",
            name="uq_eosv3_variant_binding",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_eosv3_variant_enrollment",
        "upbit_exit_optimization_shadow_v3_variant",
        ["enrollment_id"],
        schema="operation",
    )
    op.create_index(
        "ix_eosv3_variant_status",
        "upbit_exit_optimization_shadow_v3_variant",
        ["variant_id", "status"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_table(
        "upbit_exit_optimization_shadow_v3_variant", schema="operation"
    )
    op.drop_table(
        "upbit_exit_optimization_shadow_v3_enrollment", schema="operation"
    )
    op.drop_table(
        "upbit_exit_optimization_shadow_v3_policy", schema="operation"
    )
