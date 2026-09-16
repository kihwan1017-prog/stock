"""Market data gap backfill checkpoint (DB-resumable).

Revision ID: md1a2b3c4d5e
Revises: dq1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "md1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "dq1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_data_backfill_checkpoint",
        sa.Column(
            "checkpoint_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("exchange_code", sa.String(20), nullable=False),
        sa.Column("data_kind", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=False),
        sa.Column(
            "repair_status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("gap_reason", sa.String(80), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "exchange_code",
            "data_kind",
            "symbol",
            "expected_date",
            name="uq_market_data_backfill_gap",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_market_data_backfill_pending",
        "market_data_backfill_checkpoint",
        ["exchange_code", "data_kind", "repair_status"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_data_backfill_pending",
        table_name="market_data_backfill_checkpoint",
        schema="operation",
    )
    op.drop_table(
        "market_data_backfill_checkpoint",
        schema="operation",
    )
