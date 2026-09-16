"""Broker external order/trade history tables

Revision ID: h1a2b3c4d5e6
Revises: j4k5l6m7n8o9
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "j4k5l6m7n8o9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broker_external_order_history",
        sa.Column(
            "broker_external_order_history_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("broker_code", sa.String(30), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("external_order_id", sa.String(100), nullable=False),
        sa.Column("external_order_id_masked", sa.String(40), nullable=True),
        sa.Column("market_code", sa.String(40), nullable=True),
        sa.Column("side_code", sa.String(10), nullable=True),
        sa.Column("order_type_code", sa.String(30), nullable=True),
        sa.Column("order_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("requested_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("executed_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("remaining_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("paid_fee", sa.Numeric(28, 8), nullable=True),
        sa.Column("locked_amount", sa.Numeric(28, 8), nullable=True),
        sa.Column("external_status", sa.String(40), nullable=True),
        sa.Column(
            "external_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "external_done_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "raw_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "import_policy",
            sa.String(60),
            nullable=False,
            server_default="PRESERVE_REMOTE_HISTORY",
        ),
        sa.Column("source_conflict_id", sa.BigInteger(), nullable=True),
        sa.Column("imported_by", sa.String(100), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
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
            "broker_code",
            "external_order_id",
            name="uq_broker_ext_order_broker_uuid",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_broker_ext_order_uba",
        "broker_external_order_history",
        ["user_broker_account_id"],
        schema="operation",
    )
    op.create_index(
        "ix_broker_ext_order_conflict",
        "broker_external_order_history",
        ["source_conflict_id"],
        schema="operation",
    )

    op.create_table(
        "broker_external_trade_history",
        sa.Column(
            "broker_external_trade_history_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("broker_code", sa.String(30), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("external_trade_id", sa.String(100), nullable=False),
        sa.Column("external_order_id", sa.String(100), nullable=False),
        sa.Column("market_code", sa.String(40), nullable=True),
        sa.Column("side_code", sa.String(10), nullable=True),
        sa.Column("trade_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("trade_volume", sa.Numeric(28, 8), nullable=True),
        sa.Column("funds", sa.Numeric(28, 8), nullable=True),
        sa.Column("fee", sa.Numeric(28, 8), nullable=True),
        sa.Column(
            "executed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "raw_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("source_conflict_id", sa.BigInteger(), nullable=True),
        sa.Column("imported_by", sa.String(100), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "broker_code",
            "external_trade_id",
            name="uq_broker_ext_trade_broker_uuid",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_broker_ext_trade_order",
        "broker_external_trade_history",
        ["external_order_id"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_broker_ext_trade_order",
        table_name="broker_external_trade_history",
        schema="operation",
    )
    op.drop_table("broker_external_trade_history", schema="operation")
    op.drop_index(
        "ix_broker_ext_order_conflict",
        table_name="broker_external_order_history",
        schema="operation",
    )
    op.drop_index(
        "ix_broker_ext_order_uba",
        table_name="broker_external_order_history",
        schema="operation",
    )
    op.drop_table("broker_external_order_history", schema="operation")
