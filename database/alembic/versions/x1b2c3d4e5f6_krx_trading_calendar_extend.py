"""STEP 8-5-7 — Extend trading_calendar_day + sync history.

Revision ID: x1b2c3d4e5f6
Revises: w0a1b2c3d4e5
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "w0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 기존 operation.trading_calendar_day 확장 (중복 테이블 생성 금지)
    op.add_column(
        "trading_calendar_day",
        sa.Column(
            "session_type",
            sa.String(30),
            nullable=False,
            server_default="REGULAR",
        ),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column("preopen_at", sa.Time(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column("regular_open_at", sa.Time(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column("regular_close_at", sa.Time(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column("after_hours_close_at", sa.Time(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column(
            "timezone",
            sa.String(40),
            nullable=False,
            server_default="Asia/Seoul",
        ),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column("closure_reason", sa.String(200), nullable=True),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column(
            "source_type",
            sa.String(40),
            nullable=False,
            server_default="MANUAL",
        ),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column("source_reference", sa.String(200), nullable=True),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column(
            "source_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column(
            "verified_status",
            sa.String(20),
            nullable=False,
            server_default="UNVERIFIED",
        ),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column("verified_by", sa.String(100), nullable=True),
        schema="operation",
    )
    op.add_column(
        "trading_calendar_day",
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="operation",
    )

    # 기존 행: 휴장일이면 CLOSED, 아니면 REGULAR / source_type ← source_code
    op.execute(
        """
        UPDATE operation.trading_calendar_day
        SET session_type = CASE
                WHEN is_trading_day THEN 'REGULAR' ELSE 'CLOSED'
            END,
            source_type = COALESCE(NULLIF(source_code, ''), 'MANUAL'),
            verified_status = 'UNVERIFIED',
            timezone = 'Asia/Seoul',
            regular_open_at = CASE
                WHEN is_trading_day THEN TIME '09:00:00' ELSE NULL
            END,
            regular_close_at = CASE
                WHEN is_trading_day THEN TIME '15:30:00' ELSE NULL
            END
        """
    )

    op.create_check_constraint(
        "ck_trading_calendar_session_type",
        "trading_calendar_day",
        "session_type IN ("
        "'CLOSED','REGULAR','DELAYED_OPEN','EARLY_CLOSE',"
        "'SPECIAL_SESSION')",
        schema="operation",
    )
    op.create_check_constraint(
        "ck_trading_calendar_verified_status",
        "trading_calendar_day",
        "verified_status IN ("
        "'VERIFIED','UNVERIFIED','STALE','MISSING','CONFLICT')",
        schema="operation",
    )
    op.create_check_constraint(
        "ck_trading_calendar_timezone",
        "trading_calendar_day",
        "timezone <> ''",
        schema="operation",
    )
    op.create_index(
        "ix_trading_calendar_verified_date",
        "trading_calendar_day",
        ["exchange_code", "verified_status", "calendar_date"],
        schema="operation",
    )
    op.create_index(
        "ix_trading_calendar_trading_day",
        "trading_calendar_day",
        ["exchange_code", "is_trading_day", "calendar_date"],
        schema="operation",
    )

    op.create_table(
        "trading_calendar_sync_run",
        sa.Column(
            "sync_run_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("exchange_code", sa.String(20), nullable=False),
        sa.Column(
            "status_code",
            sa.String(30),
            nullable=False,
            server_default="RUNNING",
        ),
        sa.Column("trigger_type", sa.String(30), nullable=True),
        sa.Column("requested_by", sa.String(100), nullable=True),
        sa.Column("from_date", sa.Date(), nullable=True),
        sa.Column("to_date", sa.Date(), nullable=True),
        sa.Column(
            "upserted_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "conflict_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="operation",
    )
    op.create_index(
        "ix_trading_calendar_sync_run_ex",
        "trading_calendar_sync_run",
        ["exchange_code", "started_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trading_calendar_sync_run_ex",
        table_name="trading_calendar_sync_run",
        schema="operation",
    )
    op.drop_table("trading_calendar_sync_run", schema="operation")
    op.drop_index(
        "ix_trading_calendar_trading_day",
        table_name="trading_calendar_day",
        schema="operation",
    )
    op.drop_index(
        "ix_trading_calendar_verified_date",
        table_name="trading_calendar_day",
        schema="operation",
    )
    op.drop_constraint(
        "ck_trading_calendar_timezone",
        "trading_calendar_day",
        schema="operation",
        type_="check",
    )
    op.drop_constraint(
        "ck_trading_calendar_verified_status",
        "trading_calendar_day",
        schema="operation",
        type_="check",
    )
    op.drop_constraint(
        "ck_trading_calendar_session_type",
        "trading_calendar_day",
        schema="operation",
        type_="check",
    )
    for col in (
        "verified_at",
        "verified_by",
        "verified_status",
        "source_updated_at",
        "source_reference",
        "source_type",
        "closure_reason",
        "timezone",
        "after_hours_close_at",
        "regular_close_at",
        "regular_open_at",
        "preopen_at",
        "session_type",
    ):
        op.drop_column(
            "trading_calendar_day", col, schema="operation"
        )
