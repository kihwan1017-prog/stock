"""Alembic: operation.autotrading_block_event

Revision ID: ablk1hist2a3b4
Revises: nintelv1a2b3c4
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ablk1hist2a3b4"
down_revision: Union[str, Sequence[str], None] = "nintelv1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS operation")
    op.create_table(
        "autotrading_block_event",
        sa.Column(
            "event_id", sa.BigInteger(), sa.Identity(), primary_key=True
        ),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("event_kind", sa.String(40), nullable=False),
        sa.Column("fingerprint", sa.String(120), nullable=False),
        sa.Column("primary_reason_code", sa.String(80), nullable=True),
        sa.Column("primary_reason_text", sa.Text(), nullable=True),
        sa.Column(
            "secondary_reasons_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source_component", sa.String(80), nullable=True),
        sa.Column("kill_switch_scope", sa.String(40), nullable=True),
        sa.Column("kill_switch_reason", sa.String(200), nullable=True),
        sa.Column("related_event_id", sa.String(80), nullable=True),
        sa.Column("related_order_id", sa.BigInteger(), nullable=True),
        sa.Column("related_activation_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "runtime_state_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "blocked_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("unblocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_type", sa.String(40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_broker_account_id",
            "fingerprint",
            "blocked_at",
            name="uq_autotrading_block_event_fp",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_autotrading_block_event_uba_blocked",
        "autotrading_block_event",
        ["user_broker_account_id", "blocked_at"],
        schema="operation",
    )
    op.create_index(
        "ix_autotrading_block_event_uba_open",
        "autotrading_block_event",
        ["user_broker_account_id", "resolved_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_autotrading_block_event_uba_open",
        table_name="autotrading_block_event",
        schema="operation",
    )
    op.drop_index(
        "ix_autotrading_block_event_uba_blocked",
        table_name="autotrading_block_event",
        schema="operation",
    )
    op.drop_table("autotrading_block_event", schema="operation")
