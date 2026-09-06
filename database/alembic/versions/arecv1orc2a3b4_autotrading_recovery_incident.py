"""Alembic: operation.autotrading_recovery_incident

Revision ID: arecv1orc2a3b4
Revises: cgshdv1a2b3c4
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "arecv1orc2a3b4"
down_revision: Union[str, Sequence[str], None] = "cgshdv1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS operation")
    op.create_table(
        "autotrading_recovery_incident",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("incident_id", sa.String(64), nullable=False),
        sa.Column("recovery_id", sa.String(64), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("broker_code", sa.String(20), nullable=False),
        sa.Column("root_cause", sa.String(120), nullable=True),
        sa.Column("failure_event_type", sa.String(80), nullable=True),
        sa.Column("recovery_class", sa.String(8), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("eligibility", sa.String(40), nullable=True),
        sa.Column(
            "snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("evidence_path", sa.Text(), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
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
            "incident_id", name="uq_autotrading_recovery_incident_id"
        ),
        schema="operation",
    )
    op.create_index(
        "ix_autotrading_recovery_incident_uba_created",
        "autotrading_recovery_incident",
        ["user_broker_account_id", "created_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_autotrading_recovery_incident_uba_created",
        table_name="autotrading_recovery_incident",
        schema="operation",
    )
    op.drop_table("autotrading_recovery_incident", schema="operation")
