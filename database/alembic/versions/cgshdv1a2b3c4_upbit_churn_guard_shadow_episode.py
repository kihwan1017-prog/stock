"""Alembic: operation.upbit_churn_guard_shadow_episode

Revision ID: cgshdv1a2b3c4
Revises: ablk1hist2a3b4
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cgshdv1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "ablk1hist2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS operation")
    op.create_table(
        "upbit_churn_guard_shadow_episode",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "market",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'UPBIT'"),
        ),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column(
            "family",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'UPBIT_CHURN_GUARD_SHADOW_V1'"),
        ),
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'churn_guard_shadow_v1'"),
        ),
        sa.Column(
            "mode",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'SHADOW'"),
        ),
        sa.Column(
            "real_block_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("primary_classification", sa.String(64), nullable=False),
        sa.Column(
            "secondary_classifications_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "round_trip_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "loss_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "consecutive_loss_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("gross_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("fees", sa.Numeric(20, 4), nullable=True),
        sa.Column("net_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column(
            "reentry_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("min_reentry_seconds", sa.Numeric(16, 4), nullable=True),
        sa.Column("dominant_exit_reason", sa.String(64), nullable=True),
        sa.Column("last_alert_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_alert_severity", sa.String(20), nullable=True),
        sa.Column("telegram_dedupe_key", sa.String(160), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "detail_json",
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
        "ix_upbit_churn_guard_uba_status",
        "upbit_churn_guard_shadow_episode",
        ["user_broker_account_id", "status", "last_observed_at"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_churn_guard_uba_symbol_status",
        "upbit_churn_guard_shadow_episode",
        ["user_broker_account_id", "symbol", "status"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_upbit_churn_guard_uba_symbol_status",
        table_name="upbit_churn_guard_shadow_episode",
        schema="operation",
    )
    op.drop_index(
        "ix_upbit_churn_guard_uba_status",
        table_name="upbit_churn_guard_shadow_episode",
        schema="operation",
    )
    op.drop_table("upbit_churn_guard_shadow_episode", schema="operation")
