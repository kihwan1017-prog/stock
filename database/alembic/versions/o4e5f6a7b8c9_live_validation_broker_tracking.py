"""STEP 8-9A — live_validation_run broker tracking columns

Revision ID: o4e5f6a7b8c9
Revises: n3d4e5f6a7b8
Create Date: 2026-07-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "n3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "live_validation_run",
        sa.Column(
            "internal_status",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'CREATED'"),
        ),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column(
            "broker_order_status",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'NOT_SUBMITTED'"),
        ),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("broker_identifier", sa.String(120)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("broker_order_uuid", sa.String(80)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column(
            "submission_attempt_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("last_broker_query_at", sa.DateTime(timezone=True)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("status_confirmed_at", sa.DateTime(timezone=True)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("next_track_at", sa.DateTime(timezone=True)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column(
            "track_attempt_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("watch_deadline_at", sa.DateTime(timezone=True)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("filled_quantity", sa.Numeric(28, 8)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("avg_fill_price", sa.Numeric(28, 8)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("filled_amount", sa.Numeric(28, 8)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("fee_amount", sa.Numeric(28, 8)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column(
            "manual_review_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("correlation_id", sa.String(64)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("claim_owner", sa.String(80)),
        schema="trading",
    )
    op.add_column(
        "live_validation_run",
        sa.Column("claim_expires_at", sa.DateTime(timezone=True)),
        schema="trading",
    )
    op.create_index(
        "ix_live_validation_run_broker_track",
        "live_validation_run",
        ["broker_order_status", "next_track_at"],
        schema="trading",
    )
    op.create_index(
        "ix_live_validation_run_broker_identifier",
        "live_validation_run",
        ["broker_identifier"],
        unique=False,
        schema="trading",
    )
    # status_code → internal_status 백필
    op.execute(
        sa.text(
            "UPDATE trading.live_validation_run "
            "SET internal_status = status_code "
            "WHERE internal_status = 'CREATED'"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_live_validation_run_broker_identifier",
        table_name="live_validation_run",
        schema="trading",
    )
    op.drop_index(
        "ix_live_validation_run_broker_track",
        table_name="live_validation_run",
        schema="trading",
    )
    for col in (
        "claim_expires_at",
        "claim_owner",
        "correlation_id",
        "manual_review_required",
        "fee_amount",
        "filled_amount",
        "avg_fill_price",
        "filled_quantity",
        "watch_deadline_at",
        "track_attempt_count",
        "next_track_at",
        "status_confirmed_at",
        "last_broker_query_at",
        "submission_attempt_count",
        "broker_order_uuid",
        "broker_identifier",
        "broker_order_status",
        "internal_status",
    ):
        op.drop_column("live_validation_run", col, schema="trading")
