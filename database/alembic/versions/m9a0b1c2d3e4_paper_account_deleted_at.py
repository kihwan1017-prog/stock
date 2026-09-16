"""revision: m9a0b1c2d3e4

paper_account soft delete용 deleted_at 컬럼 추가.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m9a0b1c2d3e4"
down_revision = "l8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paper_account",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="trading",
    )
    op.create_index(
        "ix_trading_paper_account_deleted_at",
        "paper_account",
        ["deleted_at"],
        schema="trading",
    )
    # 기존 is_active=false 행을 soft-deleted 로 백필
    op.execute(
        sa.text(
            "UPDATE trading.paper_account "
            "SET deleted_at = COALESCE(updated_at, NOW()) "
            "WHERE is_active = false AND deleted_at IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trading_paper_account_deleted_at",
        table_name="paper_account",
        schema="trading",
    )
    op.drop_column("paper_account", "deleted_at", schema="trading")
