"""auth.user 에 email · terms_accepted_at 추가

Revision ID: a1b2c3d4e5f6
Revises: f4a5b6c7d8e9
Create Date: 2026-07-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("email", sa.String(length=255), nullable=True),
        schema="auth",
    )
    op.add_column(
        "user",
        sa.Column(
            "terms_accepted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="auth",
    )
    op.create_index(
        "ix_auth_user_email",
        "user",
        ["email"],
        unique=True,
        schema="auth",
        postgresql_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_user_email",
        table_name="user",
        schema="auth",
    )
    op.drop_column("user", "terms_accepted_at", schema="auth")
    op.drop_column("user", "email", schema="auth")
