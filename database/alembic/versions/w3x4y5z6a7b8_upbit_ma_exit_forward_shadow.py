"""Upbit MA exit forward shadow — research only, REAL policy unchanged.

Revision ID: w3x4y5z6a7b8
Revises: a8105aa410f9
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w3x4y5z6a7b8"
down_revision: Union[str, Sequence[str], None] = "a8105aa410f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_ma_exit_forward_shadow",
        sa.Column("shadow_row_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False, server_default="UPBIT"),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("binding_id", sa.BigInteger(), nullable=False),
        sa.Column("entry_order_id", sa.BigInteger(), nullable=True),
        sa.Column("entry_fill_id", sa.BigInteger(), nullable=True),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("entry_quantity", sa.Numeric(28, 12), nullable=True),
        sa.Column("entry_fee", sa.Numeric(20, 4), nullable=True),
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default="ma_dead_cross_confirm2_v1",
        ),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("baseline_exit_reason", sa.String(64), nullable=True),
        sa.Column("baseline_exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("baseline_exit_price", sa.Numeric(28, 12), nullable=True),
        sa.Column("baseline_gross_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("baseline_fee", sa.Numeric(20, 4), nullable=True),
        sa.Column("baseline_net_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column(
            "shadow_rule",
            sa.String(64),
            nullable=False,
            server_default="MA_DEAD_CROSS_CONFIRM2",
        ),
        sa.Column("shadow_first_dead_cross_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "shadow_confirmation_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("shadow_exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shadow_exit_price", sa.Numeric(28, 12), nullable=True),
        sa.Column("shadow_exit_reason", sa.String(64), nullable=True),
        sa.Column("shadow_gross_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("shadow_fee", sa.Numeric(20, 4), nullable=True),
        sa.Column("shadow_net_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("difference_net", sa.Numeric(20, 4), nullable=True),
        sa.Column(
            "secondary_shadow_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "shadow_state_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("context_as_of", sa.DateTime(timezone=True), nullable=True),
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
        schema="operation",
    )
    op.create_index(
        "ix_upbit_ma_exit_fwd_shadow_uba_sym",
        "upbit_ma_exit_forward_shadow",
        ["user_broker_account_id", "symbol"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_ma_exit_fwd_shadow_status",
        "upbit_ma_exit_forward_shadow",
        ["status"],
        schema="operation",
    )
    op.create_unique_constraint(
        "uq_upbit_ma_exit_fwd_shadow_binding",
        "upbit_ma_exit_forward_shadow",
        ["binding_id"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_table("upbit_ma_exit_forward_shadow", schema="operation")
