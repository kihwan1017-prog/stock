"""STEP72 — user preferences

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_preference",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "theme",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        sa.Column(
            "language",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'KO'"),
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'Asia/Seoul'"),
        ),
        sa.Column(
            "date_format",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'YYYY-MM-DD'"),
        ),
        sa.Column(
            "number_format",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'1,234.56'"),
        ),
        sa.Column(
            "currency",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'KRW'"),
        ),
        sa.Column(
            "default_market",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'KRX'"),
        ),
        sa.Column("default_account_id", sa.BigInteger(), nullable=True),
        sa.Column("default_watchlist_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "default_dashboard",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'Dashboard'"),
        ),
        sa.Column(
            "items_per_page",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("20"),
        ),
        sa.Column(
            "ai_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "ai_auto_summary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "ai_recommendation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "notification_enabled",
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
            "email_enabled",
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
            name="fk_user_preference_user",
            ondelete="CASCADE",
        ),
        schema="auth",
    )
    op.create_index(
        "ix_user_preference_default_account",
        "user_preference",
        ["default_account_id"],
        schema="auth",
    )
    op.create_index(
        "ix_user_preference_default_market",
        "user_preference",
        ["default_market"],
        schema="auth",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_preference_default_market",
        table_name="user_preference",
        schema="auth",
    )
    op.drop_index(
        "ix_user_preference_default_account",
        table_name="user_preference",
        schema="auth",
    )
    op.drop_table("user_preference", schema="auth")
