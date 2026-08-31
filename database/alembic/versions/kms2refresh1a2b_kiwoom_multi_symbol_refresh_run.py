"""Add kiwoom_multi_symbol_refresh_run audit table.

Revision ID: kms2refresh1a2b
Revises: kms1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "kms2refresh1a2b"
down_revision: Union[str, Sequence[str], None] = "kms1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kiwoom_multi_symbol_refresh_run",
        sa.Column("refresh_run_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("refresh_batch_id", sa.String(64), nullable=False),
        sa.Column("trigger_source", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column(
            "stats_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "timing_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_kiwoom_ms_refresh_uba_started",
        "kiwoom_multi_symbol_refresh_run",
        ["user_broker_account_id", "started_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_table("kiwoom_multi_symbol_refresh_run", schema="operation")
