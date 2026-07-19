"""create auth schema user and refresh_token tables

Revision ID: c1d2e3f4a5b6
Revises: a2b3c4d5e6f7
Create Date: 2026-07-19 16:55:00.000000

STEP1: JWT 인증 — auth.user, auth.refresh_token
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    op.create_table(
        "user",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "display_name",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "roles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[\"admin\"]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
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
            "password_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user")),
        sa.UniqueConstraint(
            "username",
            name="uq_user_username",
        ),
        schema="auth",
    )
    op.create_index(
        "ix_auth_user_username",
        "user",
        ["username"],
        schema="auth",
        unique=True,
    )

    op.create_table(
        "refresh_token",
        sa.Column(
            "refresh_token_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "jti",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "token_hash",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.user.user_id"],
            name=op.f("fk_refresh_token_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "refresh_token_id",
            name=op.f("pk_refresh_token"),
        ),
        sa.UniqueConstraint("jti", name="uq_refresh_token_jti"),
        schema="auth",
    )
    op.create_index(
        "ix_auth_refresh_token_user_id",
        "refresh_token",
        ["user_id"],
        schema="auth",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_refresh_token_user_id",
        table_name="refresh_token",
        schema="auth",
    )
    op.drop_table("refresh_token", schema="auth")
    op.drop_index(
        "ix_auth_user_username",
        table_name="user",
        schema="auth",
    )
    op.drop_table("user", schema="auth")
    op.execute("DROP SCHEMA IF EXISTS auth")
