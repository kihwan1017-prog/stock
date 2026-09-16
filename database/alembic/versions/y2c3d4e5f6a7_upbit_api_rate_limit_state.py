"""STEP 8-5-8 — Upbit API rate limit cooldown state.

Revision ID: y2c3d4e5f6a7
Revises: x1b2c3d4e5f6
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "y2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "x1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_api_rate_limit_state",
        sa.Column(
            "upbit_api_rate_limit_state_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column(
            "credential_scope_type",
            sa.String(20),
            nullable=False,
            server_default="UBA",
        ),
        sa.Column(
            "user_broker_account_id",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "endpoint_group",
            sa.String(40),
            nullable=False,
            server_default="default",
        ),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="OK",
        ),
        sa.Column("remaining_second", sa.Integer(), nullable=True),
        sa.Column("remaining_minute", sa.Integer(), nullable=True),
        sa.Column(
            "cooldown_until", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "blocked_until", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("last_retry_after_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "consecutive_rate_limit_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_request_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "last_response_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("updated_by_instance_id", sa.String(200), nullable=True),
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
            "credential_scope_type IN ('UBA', 'PUBLIC')",
            name="ck_upbit_rate_limit_scope",
        ),
        sa.CheckConstraint(
            "status IN ('OK', 'COOLDOWN', 'BLOCKED_418', 'DEFERRED')",
            name="ck_upbit_rate_limit_status",
        ),
        sa.CheckConstraint(
            "consecutive_rate_limit_count >= 0",
            name="ck_upbit_rate_limit_consecutive",
        ),
        sa.UniqueConstraint(
            "credential_scope_type",
            "user_broker_account_id",
            "endpoint_group",
            name="uq_upbit_rate_limit_scope_group",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_upbit_rate_limit_uba",
        "upbit_api_rate_limit_state",
        ["user_broker_account_id", "status"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_rate_limit_cooldown",
        "upbit_api_rate_limit_state",
        ["cooldown_until"],
        schema="operation",
    )

    # Recovery account state — next_retry 메타 (기존 컬럼 있으면 skip)
    # broker_recovery_account_state 에 next_retry_reason 추가
    op.add_column(
        "broker_recovery_account_state",
        sa.Column("next_retry_reason", sa.String(60), nullable=True),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_account_state",
        sa.Column("rate_limit_endpoint_group", sa.String(40), nullable=True),
        schema="operation",
    )


def downgrade() -> None:
    op.drop_column(
        "broker_recovery_account_state",
        "rate_limit_endpoint_group",
        schema="operation",
    )
    op.drop_column(
        "broker_recovery_account_state",
        "next_retry_reason",
        schema="operation",
    )
    op.drop_index(
        "ix_upbit_rate_limit_cooldown",
        table_name="upbit_api_rate_limit_state",
        schema="operation",
    )
    op.drop_index(
        "ix_upbit_rate_limit_uba",
        table_name="upbit_api_rate_limit_state",
        schema="operation",
    )
    op.drop_table("upbit_api_rate_limit_state", schema="operation")
