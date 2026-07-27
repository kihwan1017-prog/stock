"""STEP 8-5-3 — Broker Recovery Scheduler jobs + retry columns.

Revision ID: u8b9c0d1e2f3
Revises: t7a8b9c0d1e2
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "u8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "t7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broker_recovery_scheduler_job",
        sa.Column(
            "scheduler_job_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("job_id", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("broker_code", sa.String(30), nullable=False),
        sa.Column(
            "trigger_type",
            sa.String(30),
            nullable=False,
            server_default="CRON",
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        # CRON: "minute hour * * day_of_week" 또는 interval_minutes
        sa.Column("cron_expression", sa.String(80), nullable=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "timezone",
            sa.String(64),
            nullable=False,
            server_default="Asia/Seoul",
        ),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="180",
        ),
        sa.Column(
            "max_retries",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
        sa.Column(
            "backoff_base_seconds",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        sa.Column(
            "backoff_max_seconds",
            sa.Integer(),
            nullable=False,
            server_default="1800",
        ),
        sa.Column(
            "concurrency",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column(
            "last_status",
            sa.String(30),
            nullable=True,
        ),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
            sa.Column(
                "last_result_summary",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        sa.Column("updated_by", sa.String(100), nullable=True),
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
        sa.UniqueConstraint(
            "job_id", name="uq_broker_recovery_scheduler_job_id"
        ),
        sa.CheckConstraint(
            "trigger_type IN ('CRON','INTERVAL')",
            name="ck_recovery_sched_trigger",
        ),
        sa.CheckConstraint(
            "timeout_seconds > 0",
            name="ck_recovery_sched_timeout",
        ),
        sa.CheckConstraint(
            "max_retries >= 0",
            name="ck_recovery_sched_retries",
        ),
        sa.CheckConstraint(
            "concurrency >= 1 AND concurrency <= 10",
            name="ck_recovery_sched_concurrency",
        ),
        sa.CheckConstraint(
            "(trigger_type = 'CRON' AND cron_expression IS NOT NULL) "
            "OR (trigger_type = 'INTERVAL' AND interval_minutes IS NOT NULL)",
            name="ck_recovery_sched_trigger_fields",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_recovery_sched_job_enabled",
        "broker_recovery_scheduler_job",
        ["is_enabled"],
        schema="operation",
    )

    # 계좌별 재시도 메타
    op.add_column(
        "broker_recovery_account_state",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_account_state",
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_account_state",
        sa.Column(
            "last_error_code",
            sa.String(80),
            nullable=True,
        ),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_account_state",
        sa.Column(
            "auto_retry_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="operation",
    )

    # 시드 Job (기본값 — ADMIN이 이후 변경)
    op.execute(
        sa.text(
            """
            INSERT INTO operation.broker_recovery_scheduler_job (
                job_id, display_name, broker_code, trigger_type,
                is_enabled, cron_expression, interval_minutes, timezone,
                timeout_seconds, max_retries, backoff_base_seconds,
                backoff_max_seconds, concurrency
            ) VALUES
            (
                'broker_recovery_kiwoom_preopen',
                '키움 장시작 전 Recovery',
                'KIWOOM', 'CRON', true,
                '30 8 * * mon-fri', NULL, 'Asia/Seoul',
                180, 3, 60, 1800, 2
            ),
            (
                'broker_recovery_kiwoom_postclose',
                '키움 장종료 후 Recovery',
                'KIWOOM', 'CRON', true,
                '40 15 * * mon-fri', NULL, 'Asia/Seoul',
                240, 3, 60, 1800, 2
            ),
            (
                'broker_recovery_upbit_interval',
                '업비트 Interval Recovery',
                'UPBIT', 'INTERVAL', true,
                NULL, 20, 'Asia/Seoul',
                180, 3, 60, 1800, 2
            ),
            (
                'broker_recovery_paper_integrity',
                'Paper 정합성 Recovery',
                'PAPER', 'INTERVAL', true,
                NULL, 360, 'Asia/Seoul',
                120, 2, 120, 3600, 3
            ),
            (
                'broker_recovery_failed_retry',
                '실패 계좌 재시도 Recovery',
                'ALL', 'INTERVAL', true,
                NULL, 15, 'Asia/Seoul',
                180, 5, 60, 1800, 2
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_column(
        "broker_recovery_account_state",
        "auto_retry_enabled",
        schema="operation",
    )
    op.drop_column(
        "broker_recovery_account_state",
        "last_error_code",
        schema="operation",
    )
    op.drop_column(
        "broker_recovery_account_state",
        "next_retry_at",
        schema="operation",
    )
    op.drop_column(
        "broker_recovery_account_state",
        "retry_count",
        schema="operation",
    )
    op.drop_index(
        "ix_recovery_sched_job_enabled",
        table_name="broker_recovery_scheduler_job",
        schema="operation",
    )
    op.drop_table(
        "broker_recovery_scheduler_job", schema="operation"
    )
