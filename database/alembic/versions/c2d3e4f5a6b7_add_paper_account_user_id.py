"""paper_account.user_id 소유권 컬럼 추가 (STEP52)

Revision ID: c2d3e4f5a6b7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "paper_account",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.create_index(
        "ix_paper_account_user_id",
        "paper_account",
        ["user_id"],
        schema="trading",
    )
    op.create_foreign_key(
        "fk_paper_account_user",
        "paper_account",
        "user",
        ["user_id"],
        ["user_id"],
        source_schema="trading",
        referent_schema="auth",
        ondelete="SET NULL",
    )
    # 기존 account_id=1 을 bootstrap admin(있을 경우)에 배정
    op.execute(
        """
        UPDATE trading.paper_account AS pa
        SET user_id = u.user_id
        FROM auth."user" AS u
        WHERE pa.account_id = 1
          AND pa.user_id IS NULL
          AND u.is_active IS TRUE
          AND u.roles @> '["admin"]'::jsonb
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_paper_account_user",
        "paper_account",
        schema="trading",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_paper_account_user_id",
        table_name="paper_account",
        schema="trading",
    )
    op.drop_column("paper_account", "user_id", schema="trading")
