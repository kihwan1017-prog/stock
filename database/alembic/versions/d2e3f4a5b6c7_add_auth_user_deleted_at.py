"""add soft delete deleted_at to auth.user

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-19 17:10:00.000000

STEP2: 회원 Soft Delete
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="auth",
    )
    op.create_index(
        "ix_auth_user_deleted_at",
        "user",
        ["deleted_at"],
        schema="auth",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_user_deleted_at",
        table_name="user",
        schema="auth",
    )
    op.drop_column("user", "deleted_at", schema="auth")
