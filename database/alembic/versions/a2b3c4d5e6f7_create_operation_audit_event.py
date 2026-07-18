"""create operation audit_event table

Revision ID: a2b3c4d5e6f7
Revises: f1a9e8b7c6d5
Create Date: 2026-07-18 09:20:00.000000

STEP39-03: 운영 감사 로그.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1a9e8b7c6d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_event",
        sa.Column(
            "audit_event_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("strategy_id", sa.String(length=100), nullable=True),
        sa.Column("account_hash", sa.String(length=32), nullable=True),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "client_order_id",
            sa.String(length=50),
            nullable=True,
        ),
        sa.Column("symbol", sa.String(length=30), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "audit_event_id",
            name=op.f("pk_audit_event"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_audit_event_type_created",
        "audit_event",
        ["event_type", "created_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audit_event_type_created",
        table_name="audit_event",
        schema="operation",
    )
    op.drop_table("audit_event", schema="operation")
