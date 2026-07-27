"""STEP 8-9 — Upbit Live Validation Run

Revision ID: n3d4e5f6a7b8
Revises: m0a1b2c3d4e5
Create Date: 2026-07-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "n3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "m0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "live_validation_run",
        sa.Column(
            "live_validation_run_pk",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
        ),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("preflight_id", sa.String(64)),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "broker_code",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'UPBIT'"),
        ),
        sa.Column("market", sa.String(30), nullable=False),
        sa.Column("side_code", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(28, 8), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8)),
        sa.Column("limit_price", sa.Numeric(28, 8), nullable=False),
        sa.Column(
            "execute_live",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "status_code",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'CREATED'"),
        ),
        sa.Column("order_id", sa.BigInteger()),
        sa.Column("order_status", sa.String(40)),
        sa.Column(
            "preflight_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("request_fingerprint", sa.String(64)),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("failure_summary", sa.Text()),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("post_fill_verification_id", sa.BigInteger()),
        sa.Column("created_by", sa.String(100), nullable=False),
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
            ["user_broker_account_id"],
            ["trading.user_broker_account.user_broker_account_id"],
            name="fk_live_validation_run_uba",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_live_validation_run_idempotency"
        ),
        sa.UniqueConstraint("run_id", name="uq_live_validation_run_run_id"),
        schema="trading",
    )
    op.create_index(
        "ix_live_validation_run_uba_status",
        "live_validation_run",
        ["user_broker_account_id", "status_code"],
        schema="trading",
    )
    op.create_index(
        "ix_live_validation_run_preflight",
        "live_validation_run",
        ["preflight_id"],
        schema="trading",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_live_validation_run_preflight",
        table_name="live_validation_run",
        schema="trading",
    )
    op.drop_index(
        "ix_live_validation_run_uba_status",
        table_name="live_validation_run",
        schema="trading",
    )
    op.drop_table("live_validation_run", schema="trading")
