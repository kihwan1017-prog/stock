"""add order outbox idempotency execution tables

Revision ID: b8f4c2a19e03
Revises: 7a73b030ced6
Create Date: 2026-07-17 16:40:00.000000

Entity-DB gap 해소:
- operation.idempotency_key
- trading.order_outbox
- trading.execution
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b8f4c2a19e03"
down_revision: Union[str, Sequence[str], None] = "7a73b030ced6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idempotency_key",
        sa.Column(
            "idempotency_key",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "request_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "status_code",
            sa.String(length=20),
            server_default=sa.text("'PROCESSING'"),
            nullable=False,
        ),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint(
            "idempotency_key",
            name=op.f("pk_idempotency_key"),
        ),
        schema="operation",
    )

    op.create_table(
        "order_outbox",
        sa.Column("outbox_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status_code",
            sa.String(length=20),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "max_retry_count",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["trading.trading_order.order_id"],
            name=op.f("fk_order_outbox_order_id_trading_order"),
        ),
        sa.PrimaryKeyConstraint(
            "outbox_id",
            name=op.f("pk_order_outbox"),
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name=op.f("uq_order_outbox_idempotency_key"),
        ),
        schema="trading",
    )
    op.create_index(
        "ix_order_outbox_claim",
        "order_outbox",
        ["status_code", "next_retry_at", "outbox_id"],
        unique=False,
        schema="trading",
    )
    op.create_index(
        "ix_order_outbox_order_id",
        "order_outbox",
        ["order_id"],
        unique=False,
        schema="trading",
    )

    op.create_table(
        "execution",
        sa.Column("execution_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "broker_code",
            sa.String(length=20),
            server_default=sa.text("'KIWOOM'"),
            nullable=False,
        ),
        sa.Column("broker_order_id", sa.String(length=100), nullable=False),
        sa.Column("broker_execution_id", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("side_code", sa.String(length=20), nullable=True),
        sa.Column("execution_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("execution_quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "raw_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["trading.trading_order.order_id"],
            name=op.f("fk_execution_order_id_trading_order"),
        ),
        sa.PrimaryKeyConstraint(
            "execution_id",
            name=op.f("pk_execution"),
        ),
        sa.UniqueConstraint(
            "broker_code",
            "broker_execution_id",
            name="uq_execution_broker_execution",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_execution_order_id",
        "execution",
        ["order_id"],
        unique=False,
        schema="trading",
    )
    op.create_index(
        "ix_execution_executed_at",
        "execution",
        ["executed_at"],
        unique=False,
        schema="trading",
    )


def downgrade() -> None:
    op.drop_index("ix_execution_executed_at", table_name="execution", schema="trading")
    op.drop_index("ix_execution_order_id", table_name="execution", schema="trading")
    op.drop_table("execution", schema="trading")
    op.drop_index("ix_order_outbox_order_id", table_name="order_outbox", schema="trading")
    op.drop_index("ix_order_outbox_claim", table_name="order_outbox", schema="trading")
    op.drop_table("order_outbox", schema="trading")
    op.drop_table("idempotency_key", schema="operation")
