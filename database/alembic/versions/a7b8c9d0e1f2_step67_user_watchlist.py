"""STEP67 — user watchlist (관심종목)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column(
            "watchlist_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("symbol_name", sa.String(length=200), nullable=False),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("memo", sa.String(length=500), nullable=True),
        sa.Column("color", sa.String(length=20), nullable=True),
        sa.Column(
            "alarm_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "news_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "disclosure_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "ai_enabled",
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
            name="fk_watchlist_user",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "market",
            "symbol",
            name="uq_watchlist_user_market_symbol",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_watchlist_user_order",
        "watchlist",
        ["user_id", "display_order"],
        schema="trading",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_watchlist_user_order",
        table_name="watchlist",
        schema="trading",
    )
    op.drop_table("watchlist", schema="trading")
