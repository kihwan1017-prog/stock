"""Upbit trailing forward shadow — Alembic DDL only.

Revision ID: tr1a2b3c4d5e
Revises: pv1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "tr1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "pv1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_trailing_forward_shadow",
        sa.Column("shadow_row_id", sa.BigInteger(), sa.Identity(), primary_key=True),
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
            server_default="trailing_forward_shadow_v1",
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
            "variants_json",
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
        "ix_upbit_trail_fwd_shadow_uba_sym",
        "upbit_trailing_forward_shadow",
        ["user_broker_account_id", "symbol"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_trail_fwd_shadow_status",
        "upbit_trailing_forward_shadow",
        ["status"],
        schema="operation",
    )
    op.create_unique_constraint(
        "uq_upbit_trail_fwd_shadow_binding",
        "upbit_trailing_forward_shadow",
        ["binding_id"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_table("upbit_trailing_forward_shadow", schema="operation")
