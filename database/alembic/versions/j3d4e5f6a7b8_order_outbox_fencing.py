"""STEP 8-5-22 — order_outbox fencing columns.

Revision ID: j3d4e5f6a7b8
Revises: i2c3d4e5f6a7
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "i2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "order_outbox",
        sa.Column(
            "fencing_token",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="trading",
    )
    op.add_column(
        "order_outbox",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="trading",
    )
    op.add_column(
        "order_outbox",
        sa.Column("dispatch_intent_at", sa.DateTime(timezone=True), nullable=True),
        schema="trading",
    )
    op.add_column(
        "order_outbox",
        sa.Column("request_hash", sa.String(64), nullable=True),
        schema="trading",
    )
    op.add_column(
        "order_outbox",
        sa.Column("client_order_id", sa.String(100), nullable=True),
        schema="trading",
    )
    op.add_column(
        "order_outbox",
        sa.Column("ambiguous_at", sa.DateTime(timezone=True), nullable=True),
        schema="trading",
    )
    op.add_column(
        "order_outbox",
        sa.Column(
            "confirmation_status",
            sa.String(40),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "order_outbox",
        sa.Column(
            "confirmation_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "order_outbox",
        sa.Column("manual_review_reason", sa.Text(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "order_outbox",
        sa.Column("broker_code", sa.String(30), nullable=True),
        schema="trading",
    )
    op.add_column(
        "order_outbox",
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "order_outbox",
        sa.Column("correlation_id", sa.String(64), nullable=True),
        schema="trading",
    )
    # payload에서 client_order_id / broker / uba backfill
    op.execute(
        """
        UPDATE trading.order_outbox
        SET client_order_id = COALESCE(
              client_order_id,
              NULLIF(payload_json->>'client_order_id', '')
            ),
            broker_code = COALESCE(
              broker_code,
              NULLIF(UPPER(payload_json->>'broker_code'), '')
            ),
            user_broker_account_id = COALESCE(
              user_broker_account_id,
              NULLIF(payload_json->>'user_broker_account_id', '')::bigint
            ),
            request_hash = COALESCE(
              request_hash,
              NULLIF(payload_json->>'request_hash', '')
            )
        WHERE payload_json IS NOT NULL
        """
    )
    op.create_index(
        "ix_order_outbox_ambiguous",
        "order_outbox",
        ["status_code", "ambiguous_at"],
        schema="trading",
    )
    op.create_index(
        "ix_order_outbox_client_order",
        "order_outbox",
        ["client_order_id"],
        schema="trading",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_order_outbox_client_order",
        table_name="order_outbox",
        schema="trading",
    )
    op.drop_index(
        "ix_order_outbox_ambiguous",
        table_name="order_outbox",
        schema="trading",
    )
    for col in (
        "correlation_id",
        "user_broker_account_id",
        "broker_code",
        "manual_review_reason",
        "confirmation_checked_at",
        "confirmation_status",
        "ambiguous_at",
        "client_order_id",
        "request_hash",
        "dispatch_intent_at",
        "lease_expires_at",
        "fencing_token",
    ):
        op.drop_column("order_outbox", col, schema="trading")
