"""STEP71 — user notification inbox + subscription

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS notification")

    op.create_table(
        "notification",
        sa.Column(
            "notification_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "severity",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'INFO'"),
        ),
        sa.Column(
            "dedupe_key",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="notification",
    )
    op.create_index(
        "ix_notification_created_at",
        "notification",
        ["created_at"],
        schema="notification",
    )
    op.create_index(
        "ix_notification_event_type",
        "notification",
        ["event_type"],
        schema="notification",
    )
    op.create_index(
        "ix_notification_dedupe_key",
        "notification",
        ["dedupe_key"],
        schema="notification",
        unique=False,
    )

    op.create_table(
        "user_notification",
        sa.Column(
            "user_notification_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("notification_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_starred",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("starred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "delivery_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'PENDING'"),
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
            ["user_id"],
            ["auth.user.user_id"],
            name="fk_user_notification_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notification.notification.notification_id"],
            name="fk_user_notification_notification",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "notification_id",
            name="uq_user_notification_user_notification",
        ),
        schema="notification",
    )
    op.create_index(
        "ix_user_notification_user_read",
        "user_notification",
        ["user_id", "is_read", "is_deleted"],
        schema="notification",
    )
    op.create_index(
        "ix_user_notification_user_created",
        "user_notification",
        ["user_id", "created_at"],
        schema="notification",
    )

    op.create_table(
        "notification_subscription",
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "telegram_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "web_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "email_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("quiet_time_start", sa.String(length=5), nullable=True),
        sa.Column("quiet_time_end", sa.String(length=5), nullable=True),
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
            ["user_id"],
            ["auth.user.user_id"],
            name="fk_notification_subscription_user",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "event_type",
            name="uq_notification_subscription_user_event",
        ),
        schema="notification",
    )


def downgrade() -> None:
    op.drop_table("notification_subscription", schema="notification")
    op.drop_index(
        "ix_user_notification_user_created",
        table_name="user_notification",
        schema="notification",
    )
    op.drop_index(
        "ix_user_notification_user_read",
        table_name="user_notification",
        schema="notification",
    )
    op.drop_table("user_notification", schema="notification")
    op.drop_index(
        "ix_notification_dedupe_key",
        table_name="notification",
        schema="notification",
    )
    op.drop_index(
        "ix_notification_event_type",
        table_name="notification",
        schema="notification",
    )
    op.drop_index(
        "ix_notification_created_at",
        table_name="notification",
        schema="notification",
    )
    op.drop_table("notification", schema="notification")
