"""Exit Optimization Shadow Lab V2 — reentry cooldown table + indexes.

Revision ID: eoslabv2a1b2c3
Revises: kms3real1a2b3
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "eoslabv2a1b2c3"
down_revision: Union[str, Sequence[str], None] = "kms3real1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_post_exit_reentry_cooldown_shadow",
        sa.Column("shadow_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False, server_default="UPBIT"),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column(
            "family",
            sa.String(64),
            nullable=False,
            server_default="POST_EXIT_REENTRY_COOLDOWN_SHADOW_V1",
        ),
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default="reentry_cooldown_shadow_v1",
        ),
        sa.Column("previous_exit_order_id", sa.BigInteger(), nullable=True),
        sa.Column("previous_exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_exit_reason", sa.String(64), nullable=True),
        sa.Column("new_entry_order_id", sa.BigInteger(), nullable=False),
        sa.Column("new_entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gap_seconds", sa.Numeric(16, 4), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="OBSERVED"),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "variants_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("baseline_reentry_net", sa.Numeric(20, 4), nullable=True),
        sa.Column(
            "context_json",
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
        schema="operation",
    )
    op.create_index(
        "ix_upbit_reentry_cooldown_uba_symbol",
        "upbit_post_exit_reentry_cooldown_shadow",
        ["user_broker_account_id", "symbol"],
        schema="operation",
    )
    op.create_index(
        "uq_upbit_reentry_cooldown_new_entry",
        "upbit_post_exit_reentry_cooldown_shadow",
        ["new_entry_order_id"],
        unique=True,
        schema="operation",
    )
    # Active trailing shadow tick 성능 — 기존 테이블 index (없으면 생성)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_upbit_trailing_fwd_status_uba
        ON operation.upbit_trailing_forward_shadow (status, user_broker_account_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_upbit_trailing_fwd_entry_order
        ON operation.upbit_trailing_forward_shadow (entry_order_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS operation.ix_upbit_trailing_fwd_entry_order")
    op.execute("DROP INDEX IF EXISTS operation.ix_upbit_trailing_fwd_status_uba")
    op.drop_index(
        "uq_upbit_reentry_cooldown_new_entry",
        table_name="upbit_post_exit_reentry_cooldown_shadow",
        schema="operation",
    )
    op.drop_index(
        "ix_upbit_reentry_cooldown_uba_symbol",
        table_name="upbit_post_exit_reentry_cooldown_shadow",
        schema="operation",
    )
    op.drop_table("upbit_post_exit_reentry_cooldown_shadow", schema="operation")
