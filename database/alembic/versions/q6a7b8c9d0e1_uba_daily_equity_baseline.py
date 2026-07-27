"""STEP 8-9C-4 — UBA daily equity baseline table."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "p5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS operation"))
    op.create_table(
        "uba_daily_equity_baseline",
        sa.Column("baseline_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column(
            "currency_code",
            sa.String(length=10),
            server_default=sa.text("'KRW'"),
            nullable=False,
        ),
        sa.Column("opening_equity", sa.Numeric(20, 2), nullable=False),
        sa.Column(
            "source_code",
            sa.String(length=40),
            server_default=sa.text("'FIRST_OBSERVED'"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=80), nullable=True),
        sa.Column("broker_code", sa.String(length=20), nullable=True),
        sa.Column(
            "baseline_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.UniqueConstraint(
            "user_broker_account_id",
            "trading_date",
            "currency_code",
            name="uq_uba_daily_equity_baseline_day",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_uba_daily_equity_baseline_uba",
        "uba_daily_equity_baseline",
        ["user_broker_account_id"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_uba_daily_equity_baseline_uba",
        table_name="uba_daily_equity_baseline",
        schema="operation",
    )
    op.drop_table("uba_daily_equity_baseline", schema="operation")
