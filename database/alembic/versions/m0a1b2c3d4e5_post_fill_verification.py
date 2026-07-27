"""STEP 8-8A — Post-Fill Verification Alembic.

Revision ID: m0a1b2c3d4e5
Revises: l9c0d1e2f3a4
Create Date: 2026-07-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "m0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "l9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "post_fill_verification",
        sa.Column(
            "verification_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
        ),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("execution_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("broker_code", sa.String(30), nullable=False),
        sa.Column("symbol", sa.String(30), nullable=False),
        sa.Column(
            "expected_position",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "expected_cash_delta", sa.Numeric(28, 8), nullable=True
        ),
        sa.Column(
            "status_code",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("last_error_summary", sa.Text()),
        sa.Column("run_id", sa.String(80)),
        sa.Column("correlation_id", sa.String(80)),
        sa.Column("claimed_by", sa.String(200)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "broker_down_notified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "detail",
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
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["trading.trading_order.order_id"],
            name="fk_post_fill_verification_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_broker_account_id"],
            ["trading.user_broker_account.user_broker_account_id"],
            name="fk_post_fill_verification_uba",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_post_fill_verification_idempotency",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_post_fill_verification_due",
        "post_fill_verification",
        ["status_code", "next_retry_at"],
        schema="trading",
    )
    op.create_index(
        "ix_post_fill_verification_uba",
        "post_fill_verification",
        ["user_broker_account_id", "status_code"],
        schema="trading",
    )
    op.create_index(
        "ix_post_fill_verification_order",
        "post_fill_verification",
        ["order_id"],
        schema="trading",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_post_fill_verification_order",
        table_name="post_fill_verification",
        schema="trading",
    )
    op.drop_index(
        "ix_post_fill_verification_uba",
        table_name="post_fill_verification",
        schema="trading",
    )
    op.drop_index(
        "ix_post_fill_verification_due",
        table_name="post_fill_verification",
        schema="trading",
    )
    op.drop_table("post_fill_verification", schema="trading")
