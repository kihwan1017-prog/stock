"""MA Dead Cross Optimization Shadow Lab V1 — Alembic DDL.

Revision ID: madcv1lab1a2b3
Revises: pislabv1a2b3
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "madcv1lab1a2b3"
down_revision: Union[str, Sequence[str], None] = "pislabv1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_profitability_ma_dc_event",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("binding_id", sa.BigInteger(), nullable=False),
        sa.Column("entry_order_id", sa.BigInteger(), nullable=True),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_price", sa.Numeric(28, 12), nullable=True),
        sa.Column("baseline_exit_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_exit_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("baseline_net_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("baseline_fees", sa.Numeric(20, 4), nullable=True),
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
        sa.Column(
            "variant_outcomes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "path_state_json",
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
        sa.UniqueConstraint(
            "user_broker_account_id",
            "binding_id",
            name="uq_pislab_ma_dc_binding",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_pislab_ma_dc_uba_at",
        "upbit_profitability_ma_dc_event",
        ["user_broker_account_id", "baseline_exit_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pislab_ma_dc_uba_at",
        table_name="upbit_profitability_ma_dc_event",
        schema="operation",
    )
    op.drop_table("upbit_profitability_ma_dc_event", schema="operation")
