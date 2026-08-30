"""Google OAuth V1 — external identity + login state/handoff.

Revision ID: ggl1oauth2v1a2b3
Revises: rep1v2a3b4c5d6
Create Date: 2026-08-30

auth.user_external_identity: Google (provider, subject) ↔ auth.user
auth.oauth_login_state: OAuth state/nonce (short TTL)
auth.oauth_handoff: one-time FE exchange code after callback
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ggl1oauth2v1a2b3"
down_revision: Union[str, Sequence[str], None] = "rep1v2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_external_identity",
        sa.Column("identity_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("auth.user.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_subject", sa.String(255), nullable=False),
        sa.Column("email_snapshot", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_auth_user_external_identity_provider_subject",
        ),
        schema="auth",
    )
    op.create_index(
        "ix_auth_user_external_identity_user_id",
        "user_external_identity",
        ["user_id"],
        schema="auth",
    )

    op.create_table(
        "oauth_login_state",
        sa.Column("state", sa.String(64), primary_key=True),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("next_path", sa.String(512), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="auth",
    )

    op.create_table(
        "oauth_handoff",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("auth.user.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("next_path", sa.String(512), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="auth",
    )


def downgrade() -> None:
    op.drop_table("oauth_handoff", schema="auth")
    op.drop_table("oauth_login_state", schema="auth")
    op.drop_index(
        "ix_auth_user_external_identity_user_id",
        table_name="user_external_identity",
        schema="auth",
    )
    op.drop_table("user_external_identity", schema="auth")
