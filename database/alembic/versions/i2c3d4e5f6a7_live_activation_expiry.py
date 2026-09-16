"""STEP 8-5-21 — LIVE Activation expiry fields.

Revision ID: i2c3d4e5f6a7
Revises: h1b2c3d4e5f6
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "h1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "live_trading_transition",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="operation",
    )
    op.add_column(
        "live_trading_transition",
        sa.Column(
            "activation_status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        schema="operation",
    )
    op.add_column(
        "live_trading_transition",
        sa.Column("reason", sa.Text(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "live_trading_transition",
        sa.Column(
            "scope",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'BROKER'"),
        ),
        schema="operation",
    )
    op.add_column(
        "live_trading_transition",
        sa.Column(
            "broker_code",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'KIWOOM'"),
        ),
        schema="operation",
    )
    op.add_column(
        "live_trading_transition",
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        schema="operation",
    )
    # 기존 enabled 행 → ACTIVE, 만료 없으면 즉시 만료 처리 유도(재승인)
    op.execute(
        """
        UPDATE operation.live_trading_transition
        SET activation_status = CASE
              WHEN enabled THEN 'ACTIVE'
              WHEN disabled_at IS NOT NULL THEN 'DISABLED'
              ELSE 'PENDING'
            END
        """
    )


def downgrade() -> None:
    op.drop_column(
        "live_trading_transition", "user_broker_account_id", schema="operation"
    )
    op.drop_column("live_trading_transition", "broker_code", schema="operation")
    op.drop_column("live_trading_transition", "scope", schema="operation")
    op.drop_column("live_trading_transition", "reason", schema="operation")
    op.drop_column(
        "live_trading_transition", "activation_status", schema="operation"
    )
    op.drop_column("live_trading_transition", "expires_at", schema="operation")
