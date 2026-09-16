"""Profitability Improvement Shadow Lab V1 — Alembic DDL.

Revision ID: pislabv1a2b3
Revises: eosv3lab1a2b3
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "pislabv1a2b3"
down_revision: Union[str, Sequence[str], None] = "eosv3lab1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_profitability_candidate_refresh",
        sa.Column("refresh_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("scanner_run_id", sa.String(80), nullable=False),
        sa.Column("selection_id", sa.BigInteger(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default="profitability_improvement_shadow_v1",
        ),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "status", sa.String(40), nullable=False, server_default="PENDING_OUTCOME"
        ),
        sa.Column(
            "universe_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "rankings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "outcomes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
            "user_broker_account_id",
            "scanner_run_id",
            name="uq_pislab_cand_refresh_run",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_pislab_cand_refresh_uba_obs",
        "upbit_profitability_candidate_refresh",
        ["user_broker_account_id", "observed_at"],
        schema="operation",
    )

    op.create_table(
        "upbit_profitability_exit_enrollment",
        sa.Column("enrollment_id", sa.BigInteger(), sa.Identity(), primary_key=True),
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
            server_default="profitability_improvement_shadow_v1",
        ),
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
            "enrolled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
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
        sa.UniqueConstraint("binding_id", name="uq_pislab_exit_enrollment_binding"),
        schema="operation",
    )
    op.create_index(
        "ix_pislab_exit_enroll_uba",
        "upbit_profitability_exit_enrollment",
        ["user_broker_account_id"],
        schema="operation",
    )
    op.create_index(
        "ix_pislab_exit_enroll_status",
        "upbit_profitability_exit_enrollment",
        ["status"],
        schema="operation",
    )

    op.create_table(
        "upbit_profitability_exit_variant",
        sa.Column("variant_row_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("enrollment_id", sa.BigInteger(), nullable=False),
        sa.Column("binding_id", sa.BigInteger(), nullable=False),
        sa.Column("variant_id", sa.String(8), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="ACTIVE"),
        sa.Column("shadow_exit_reason", sa.String(64), nullable=True),
        sa.Column("shadow_exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shadow_exit_price", sa.Numeric(28, 12), nullable=True),
        sa.Column("shadow_gross_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("shadow_fees", sa.Numeric(20, 4), nullable=True),
        sa.Column("shadow_net_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("shadow_holding_seconds", sa.Numeric(18, 3), nullable=True),
        sa.Column("shadow_mfe_pct", sa.Numeric(18, 6), nullable=True),
        sa.Column("net_delta", sa.Numeric(20, 4), nullable=True),
        sa.Column("defer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "state_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
            "binding_id", "variant_id", name="uq_pislab_exit_variant_binding"
        ),
        schema="operation",
    )
    op.create_index(
        "ix_pislab_exit_variant_enroll",
        "upbit_profitability_exit_variant",
        ["enrollment_id"],
        schema="operation",
    )

    op.create_table(
        "upbit_profitability_reentry_event",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("prior_exit_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prior_exit_binding_id", sa.BigInteger(), nullable=True),
        sa.Column("reentry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reentry_delay_seconds", sa.Numeric(18, 3), nullable=False),
        sa.Column("entry_order_id", sa.BigInteger(), nullable=True),
        sa.Column("binding_id", sa.BigInteger(), nullable=True),
        sa.Column("real_net_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("real_fees", sa.Numeric(20, 4), nullable=True),
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default="profitability_improvement_shadow_v1",
        ),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "status", sa.String(40), nullable=False, server_default="PENDING_OUTCOME"
        ),
        sa.Column(
            "variant_decisions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "post_exit_returns_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
            "user_broker_account_id",
            "entry_order_id",
            name="uq_pislab_reentry_entry_order",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_pislab_reentry_uba_obs",
        "upbit_profitability_reentry_event",
        ["user_broker_account_id", "reentry_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_table("upbit_profitability_reentry_event", schema="operation")
    op.drop_table("upbit_profitability_exit_variant", schema="operation")
    op.drop_table("upbit_profitability_exit_enrollment", schema="operation")
    op.drop_table("upbit_profitability_candidate_refresh", schema="operation")
