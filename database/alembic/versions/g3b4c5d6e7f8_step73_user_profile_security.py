"""STEP73 — user profile fields + session metadata + telegram link stub

Revision ID: g3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("nickname", sa.String(length=50), nullable=True),
        schema="auth",
    )
    op.add_column(
        "user",
        sa.Column("profile_image_url", sa.String(length=500), nullable=True),
        schema="auth",
    )
    op.add_column(
        "user",
        sa.Column("bio", sa.String(length=500), nullable=True),
        schema="auth",
    )
    op.add_column(
        "user",
        sa.Column(
            "locale",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'KO'"),
        ),
        schema="auth",
    )
    op.add_column(
        "user",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="auth",
    )
    op.add_column(
        "user",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        schema="auth",
    )
    op.create_index(
        "ix_auth_user_nickname",
        "user",
        ["nickname"],
        unique=False,
        schema="auth",
    )

    op.add_column(
        "refresh_token",
        sa.Column(
            "session_public_id",
            sa.String(length=36),
            nullable=True,
        ),
        schema="auth",
    )
    op.add_column(
        "refresh_token",
        sa.Column("device_name", sa.String(length=100), nullable=True),
        schema="auth",
    )
    op.add_column(
        "refresh_token",
        sa.Column("browser_name", sa.String(length=80), nullable=True),
        schema="auth",
    )
    op.add_column(
        "refresh_token",
        sa.Column("operating_system", sa.String(length=80), nullable=True),
        schema="auth",
    )
    op.add_column(
        "refresh_token",
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        schema="auth",
    )
    op.add_column(
        "refresh_token",
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        schema="auth",
    )
    op.add_column(
        "refresh_token",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        schema="auth",
    )
    op.add_column(
        "refresh_token",
        sa.Column("revoke_reason", sa.String(length=80), nullable=True),
        schema="auth",
    )

    # 기존 행에 public id backfill
    op.execute(
        """
        UPDATE auth.refresh_token
        SET session_public_id = gen_random_uuid()::text
        WHERE session_public_id IS NULL
        """
    )
    op.alter_column(
        "refresh_token",
        "session_public_id",
        nullable=False,
        schema="auth",
    )
    op.create_index(
        "uq_refresh_token_session_public_id",
        "refresh_token",
        ["session_public_id"],
        unique=True,
        schema="auth",
    )
    op.create_index(
        "ix_refresh_token_user_revoked",
        "refresh_token",
        ["user_id", "revoked_at"],
        schema="auth",
    )

    op.create_table(
        "user_connection",
        sa.Column(
            "connection_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("connection_type", sa.String(length=30), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'NOT_CONNECTED'"),
        ),
        sa.Column("external_ref_masked", sa.String(length=100), nullable=True),
        sa.Column(
            "external_ref_hash",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "meta_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
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
            name="fk_user_connection_user",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "connection_type",
            name="uq_user_connection_user_type",
        ),
        schema="auth",
    )
    op.create_index(
        "ix_user_connection_user_status",
        "user_connection",
        ["user_id", "status"],
        schema="auth",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_connection_user_status",
        table_name="user_connection",
        schema="auth",
    )
    op.drop_table("user_connection", schema="auth")

    op.drop_index(
        "ix_refresh_token_user_revoked",
        table_name="refresh_token",
        schema="auth",
    )
    op.drop_index(
        "uq_refresh_token_session_public_id",
        table_name="refresh_token",
        schema="auth",
    )
    op.drop_column("refresh_token", "revoke_reason", schema="auth")
    op.drop_column("refresh_token", "last_used_at", schema="auth")
    op.drop_column("refresh_token", "user_agent", schema="auth")
    op.drop_column("refresh_token", "ip_address", schema="auth")
    op.drop_column("refresh_token", "operating_system", schema="auth")
    op.drop_column("refresh_token", "browser_name", schema="auth")
    op.drop_column("refresh_token", "device_name", schema="auth")
    op.drop_column("refresh_token", "session_public_id", schema="auth")

    op.drop_index("ix_auth_user_nickname", table_name="user", schema="auth")
    op.drop_column("user", "last_login_at", schema="auth")
    op.drop_column("user", "email_verified", schema="auth")
    op.drop_column("user", "locale", schema="auth")
    op.drop_column("user", "bio", schema="auth")
    op.drop_column("user", "profile_image_url", schema="auth")
    op.drop_column("user", "nickname", schema="auth")
