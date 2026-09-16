"""STEP 8-5-6 — Distributed Recovery Lock (lease + fencing).

Revision ID: w0a1b2c3d4e5
Revises: v9c0d1e2f3a4
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "w0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "v9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broker_recovery_lock",
        sa.Column(
            "broker_recovery_lock_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("lock_scope_key", sa.String(80), nullable=False),
        sa.Column("account_kind", sa.String(20), nullable=False),
        sa.Column(
            "account_id",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("paper_account_id", sa.BigInteger(), nullable=True),
        sa.Column("broker_code", sa.String(30), nullable=False),
        sa.Column(
            "market_type",
            sa.String(20),
            nullable=False,
            server_default="ALL",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="FREE",
        ),
        sa.Column("owner_instance_id", sa.String(200), nullable=True),
        sa.Column("lease_id", sa.String(64), nullable=True),
        sa.Column(
            "fencing_token",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(40), nullable=True),
        sa.Column("recovery_run_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "status IN ('FREE', 'HELD', 'RELEASED')",
            name="ck_broker_recovery_lock_status",
        ),
        sa.CheckConstraint(
            "fencing_token >= 0",
            name="ck_broker_recovery_lock_fencing",
        ),
        sa.CheckConstraint(
            "account_kind IN ('PAPER', 'USER_BROKER', 'SYSTEM')",
            name="ck_broker_recovery_lock_kind",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_run_id"],
            ["operation.broker_recovery_run.broker_recovery_run_id"],
            name="fk_recovery_lock_run",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "lock_scope_key",
            name="uq_broker_recovery_lock_scope",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_broker_recovery_lock_status_expires",
        "broker_recovery_lock",
        ["status", "lease_expires_at"],
        schema="operation",
    )
    op.create_index(
        "ix_broker_recovery_lock_held",
        "broker_recovery_lock",
        ["status"],
        schema="operation",
        postgresql_where=sa.text("status = 'HELD'"),
    )
    op.create_index(
        "ix_broker_recovery_lock_broker",
        "broker_recovery_lock",
        ["broker_code", "status"],
        schema="operation",
    )

    # Recovery Run에 fencing / owner 메타 (기존 데이터 보존, backfill 없음)
    op.add_column(
        "broker_recovery_run",
        sa.Column("fencing_token", sa.BigInteger(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column("lock_scope_key", sa.String(80), nullable=True),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column("owner_instance_id", sa.String(200), nullable=True),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column("lease_id", sa.String(64), nullable=True),
        schema="operation",
    )


def downgrade() -> None:
    op.drop_column("broker_recovery_run", "lease_id", schema="operation")
    op.drop_column(
        "broker_recovery_run", "owner_instance_id", schema="operation"
    )
    op.drop_column(
        "broker_recovery_run", "lock_scope_key", schema="operation"
    )
    op.drop_column(
        "broker_recovery_run", "fencing_token", schema="operation"
    )
    op.drop_index(
        "ix_broker_recovery_lock_broker",
        table_name="broker_recovery_lock",
        schema="operation",
    )
    op.drop_index(
        "ix_broker_recovery_lock_held",
        table_name="broker_recovery_lock",
        schema="operation",
    )
    op.drop_index(
        "ix_broker_recovery_lock_status_expires",
        table_name="broker_recovery_lock",
        schema="operation",
    )
    op.drop_table("broker_recovery_lock", schema="operation")
