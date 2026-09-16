"""STEP66 — portfolio_snapshot 일별 자산 스냅샷

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshot",
        sa.Column(
            "snapshot_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column(
            "snapshot_time",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "cash",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "market_value",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_asset",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "invested_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "realized_profit",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unrealized_profit",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "daily_profit",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "daily_profit_rate",
            sa.Numeric(12, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_return_rate",
            sa.Numeric(12, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "position_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "mode_code",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'PAPER'"),
        ),
        sa.Column(
            "valuation_mode",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'mark_to_market'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.user.user_id"],
            name="fk_portfolio_snapshot_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading.paper_account.account_id"],
            name="fk_portfolio_snapshot_account",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "account_id",
            "snapshot_date",
            "mode_code",
            name="uq_portfolio_snapshot_account_date_mode",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_portfolio_snapshot_user_date",
        "portfolio_snapshot",
        ["user_id", "snapshot_date"],
        schema="trading",
    )
    op.create_index(
        "ix_portfolio_snapshot_account_date",
        "portfolio_snapshot",
        ["account_id", "snapshot_date"],
        schema="trading",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portfolio_snapshot_account_date",
        table_name="portfolio_snapshot",
        schema="trading",
    )
    op.drop_index(
        "ix_portfolio_snapshot_user_date",
        table_name="portfolio_snapshot",
        schema="trading",
    )
    op.drop_table("portfolio_snapshot", schema="trading")
