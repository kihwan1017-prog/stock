"""STEP 8-5-11 — KRX Calendar Change Request tables + day revision.

Revision ID: z3d4e5f6a7b8
Revises: y2c3d4e5f6a7
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "z3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "y2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trading_calendar_change_request",
        sa.Column(
            "change_request_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("exchange_code", sa.String(20), nullable=False),
        sa.Column("market_date", sa.Date(), nullable=False),
        sa.Column("change_type", sa.String(40), nullable=False),
        sa.Column(
            "requested_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "current_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.String(200), nullable=True),
        sa.Column(
            "source_published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "emergency",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("conflict_message", sa.String(500), nullable=True),
        sa.Column("expected_revision", sa.Integer(), nullable=True),
        sa.Column("applied_revision", sa.Integer(), nullable=True),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("reviewed_by", sa.String(100), nullable=True),
        sa.Column(
            "reviewed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("review_comment", sa.String(500), nullable=True),
        sa.Column("applied_by", sa.String(100), nullable=True),
        sa.Column(
            "applied_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("rejected_reason", sa.String(500), nullable=True),
        sa.Column("supersedes_request_id", sa.BigInteger(), nullable=True),
        sa.Column("rollback_of_request_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "scheduler_recompute_status", sa.String(40), nullable=True
        ),
        sa.Column(
            "scheduler_recompute_error", sa.String(500), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_calendar_change_req_ex_date_status",
        "trading_calendar_change_request",
        ["exchange_code", "market_date", "status"],
        schema="operation",
    )
    op.create_index(
        "ix_calendar_change_req_status",
        "trading_calendar_change_request",
        ["status"],
        schema="operation",
    )

    op.create_table(
        "trading_calendar_day_history",
        sa.Column(
            "history_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("exchange_code", sa.String(20), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("change_request_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "before_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "after_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("source_type", sa.String(40), nullable=True),
        sa.Column(
            "emergency",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("applied_by", sa.String(100), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "rollback_target",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.ForeignKeyConstraint(
            ["change_request_id"],
            ["operation.trading_calendar_change_request.change_request_id"],
            name="fk_calendar_history_request",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "exchange_code",
            "calendar_date",
            "revision",
            name="uq_calendar_day_history_rev",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_calendar_day_history_ex_date",
        "trading_calendar_day_history",
        ["exchange_code", "calendar_date"],
        schema="operation",
    )

    # 기존 Calendar Day에 Revision 부여 (VERIFIED 상태 유지)
    op.add_column(
        "trading_calendar_day",
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column(
            "active_change_request_id", sa.BigInteger(), nullable=True
        ),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column(
            "last_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="operation",
    )
    op.execute(
        sa.text(
            """
            UPDATE operation.trading_calendar_day
            SET revision = 1
            WHERE revision IS NULL OR revision < 1
            """
        )
    )


def downgrade() -> None:
    op.drop_column(
        "trading_calendar_day", "last_changed_at", schema="operation"
    )
    op.drop_column(
        "trading_calendar_day",
        "active_change_request_id",
        schema="operation",
    )
    op.drop_column("trading_calendar_day", "revision", schema="operation")
    op.drop_index(
        "ix_calendar_day_history_ex_date",
        table_name="trading_calendar_day_history",
        schema="operation",
    )
    op.drop_table("trading_calendar_day_history", schema="operation")
    op.drop_index(
        "ix_calendar_change_req_status",
        table_name="trading_calendar_change_request",
        schema="operation",
    )
    op.drop_index(
        "ix_calendar_change_req_ex_date_status",
        table_name="trading_calendar_change_request",
        schema="operation",
    )
    op.drop_table("trading_calendar_change_request", schema="operation")
