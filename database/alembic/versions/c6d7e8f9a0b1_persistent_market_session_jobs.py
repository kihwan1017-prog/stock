"""STEP 8-5-15 — Persistent Market Session Jobs (DB Source of Truth).

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0

`calendar_scheduler_recompute._DYNAMIC_JOBS`(프로세스 메모리)를 대체하는
`operation.market_session_job` / `operation.market_session_job_run` 테이블을
추가한다. Backfill은 오늘부터 `days_ahead`(기본 7일)까지의 VERIFIED KRX
거래일에서 Preopen/Postclose/Snapshot/Settlement/AI 후보 Job을 생성하며,
과거로 확정된(=Catch-up 대상이 아닌) 시각은 생성하지 않는다.

주의: Backfill 시각 계산은 마이그레이션 실행 시점의 고정 오프셋
(Preopen -30분 / Postclose +10분 / Snapshot +10분 / Settlement +20분 /
AI +30분 — `SessionOffsetConfig` 기본값과 동일)을 사용한다. 실제 운영
오프셋(`.env` 설정)이 기본값과 다르면, 애플리케이션 기동 후 최초 Calendar
재계산(`recompute_krx_session_jobs`)에서 실제 설정 기준으로 다시 보정된다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, Sequence[str], None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Backfill 창 (오늘 포함 며칠 앞까지) — STEP 8-5-15 요구사항 기본값
_BACKFILL_DAYS_AHEAD = 7


def upgrade() -> None:
    op.create_table(
        "market_session_job",
        sa.Column(
            "market_session_job_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("exchange_code", sa.String(20), nullable=False),
        sa.Column("market_date", sa.Date(), nullable=False),
        sa.Column("calendar_revision", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(40), nullable=False),
        sa.Column("job_key", sa.String(120), nullable=False),
        sa.Column(
            "scheduled_for", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "status_code",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'SCHEDULED'"),
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
        sa.Column(
            "next_retry_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("claimed_by", sa.String(200), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "claim_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("run_token", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column(
            "superseded_by_job_id", sa.BigInteger(), nullable=True
        ),
        sa.Column(
            "superseded_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("depends_on_job_id", sa.BigInteger(), nullable=True),
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
        sa.UniqueConstraint("job_key", name="uq_market_session_job_key"),
        sa.UniqueConstraint(
            "exchange_code",
            "market_date",
            "job_type",
            "calendar_revision",
            name="uq_market_session_job_natural_key",
        ),
        sa.CheckConstraint(
            "calendar_revision >= 1", name="ck_market_session_job_revision"
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_market_session_job_attempt_count"
        ),
        sa.CheckConstraint(
            "max_attempts >= 1", name="ck_market_session_job_max_attempts"
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_job_id"],
            ["operation.market_session_job.market_session_job_id"],
            name="fk_market_session_job_superseded_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_job_id"],
            ["operation.market_session_job.market_session_job_id"],
            name="fk_market_session_job_depends_on",
            ondelete="SET NULL",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_market_session_job_due",
        "market_session_job",
        ["status_code", "scheduled_for"],
        schema="operation",
    )
    op.create_index(
        "ix_market_session_job_claim_expires",
        "market_session_job",
        ["claim_expires_at"],
        schema="operation",
    )
    op.create_index(
        "ix_market_session_job_exchange_date",
        "market_session_job",
        ["exchange_code", "market_date"],
        schema="operation",
    )
    op.create_index(
        "ix_market_session_job_revision",
        "market_session_job",
        ["exchange_code", "market_date", "calendar_revision"],
        schema="operation",
    )

    op.create_table(
        "market_session_job_run",
        sa.Column(
            "market_session_job_run_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column(
            "market_session_job_id", sa.BigInteger(), nullable=False
        ),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("instance_id", sa.String(200), nullable=True),
        sa.Column("run_token", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_code", sa.String(20), nullable=False),
        sa.Column("result_code", sa.String(80), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("calendar_revision", sa.Integer(), nullable=True),
        sa.Column(
            "scheduled_for", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "actual_started_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("lag_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["market_session_job_id"],
            ["operation.market_session_job.market_session_job_id"],
            name="fk_market_session_job_run_job",
            ondelete="CASCADE",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_market_session_job_run_job",
        "market_session_job_run",
        ["market_session_job_id"],
        schema="operation",
    )
    op.create_index(
        "ix_market_session_job_run_created",
        "market_session_job_run",
        ["created_at"],
        schema="operation",
    )

    _backfill()


def _backfill() -> None:
    bind = op.get_bind()

    plans_sql = r"""
        WITH days AS (
            SELECT calendar_date, revision, regular_open_at, regular_close_at
            FROM operation.trading_calendar_day
            WHERE exchange_code = 'KRX'
              AND is_trading_day = true
              AND verified_status = 'VERIFIED'
              AND calendar_date BETWEEN CURRENT_DATE
                  AND CURRENT_DATE + make_interval(days => :days_ahead)
              AND regular_open_at IS NOT NULL
              AND regular_close_at IS NOT NULL
        ),
        plans AS (
            SELECT calendar_date, revision, 'KRX_PREOPEN_RECOVERY' AS job_type,
                   (calendar_date + regular_open_at) AT TIME ZONE 'Asia/Seoul'
                       - INTERVAL '30 minutes' AS scheduled_for
            FROM days
            UNION ALL
            SELECT calendar_date, revision, 'KRX_POSTCLOSE_RECOVERY',
                   (calendar_date + regular_close_at) AT TIME ZONE 'Asia/Seoul'
                       + INTERVAL '10 minutes'
            FROM days
            UNION ALL
            SELECT calendar_date, revision, 'KRX_EQUITY_SNAPSHOT',
                   (calendar_date + regular_close_at) AT TIME ZONE 'Asia/Seoul'
                       + INTERVAL '10 minutes'
            FROM days
            UNION ALL
            SELECT calendar_date, revision, 'KRX_SETTLEMENT',
                   (calendar_date + regular_close_at) AT TIME ZONE 'Asia/Seoul'
                       + INTERVAL '20 minutes'
            FROM days
            UNION ALL
            SELECT calendar_date, revision, 'KRX_AI_ANALYSIS',
                   (calendar_date + regular_close_at) AT TIME ZONE 'Asia/Seoul'
                       + INTERVAL '30 minutes'
            FROM days
        ),
        eligible AS (
            SELECT calendar_date, revision, job_type, scheduled_for,
                   'KRX:' || calendar_date::text || ':' || job_type
                       || '\:rev' || revision::text AS job_key
            FROM plans
            WHERE scheduled_for >= NOW() - INTERVAL '2 minutes'
               OR (
                    job_type IN (
                        'KRX_POSTCLOSE_RECOVERY', 'KRX_EQUITY_SNAPSHOT',
                        'KRX_SETTLEMENT', 'KRX_AI_ANALYSIS'
                    )
                    AND scheduled_for >= NOW() - INTERVAL '3 hours'
               )
        ),
        inserted AS (
            INSERT INTO operation.market_session_job (
                exchange_code, market_date, calendar_revision, job_type,
                job_key, scheduled_for, status_code, payload, priority
            )
            SELECT 'KRX', calendar_date, revision, job_type, job_key,
                   scheduled_for, 'SCHEDULED', '{}'::jsonb, 100
            FROM eligible
            ON CONFLICT (job_key) DO NOTHING
            RETURNING job_type
        )
        SELECT job_type, count(*) AS cnt FROM inserted GROUP BY job_type
        ORDER BY job_type
    """
    rows = list(
        bind.execute(
            sa.text(plans_sql), {"days_ahead": _BACKFILL_DAYS_AHEAD}
        )
    )

    # AI_ANALYSIS → EQUITY_SNAPSHOT 동일 (exchange, date, revision) 의존관계 연결
    bind.execute(
        sa.text(
            """
            UPDATE operation.market_session_job AS ai
            SET depends_on_job_id = snap.market_session_job_id
            FROM operation.market_session_job AS snap
            WHERE ai.job_type = 'KRX_AI_ANALYSIS'
              AND snap.job_type = 'KRX_EQUITY_SNAPSHOT'
              AND ai.exchange_code = snap.exchange_code
              AND ai.market_date = snap.market_date
              AND ai.calendar_revision = snap.calendar_revision
              AND ai.depends_on_job_id IS NULL
            """
        )
    )

    total = sum(int(r.cnt) for r in rows)
    detail = ", ".join(f"{r.job_type}={r.cnt}" for r in rows) or "none"
    # STEP 8-5-15 Backfill 결과 — 운영 Migration 로그에서 확인 가능하도록 고지.
    print(
        f"[STEP 8-5-15] backfill: total={total}, by_type=({detail}), "
        f"days_ahead={_BACKFILL_DAYS_AHEAD}"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_session_job_run_created",
        table_name="market_session_job_run",
        schema="operation",
    )
    op.drop_index(
        "ix_market_session_job_run_job",
        table_name="market_session_job_run",
        schema="operation",
    )
    op.drop_table("market_session_job_run", schema="operation")

    op.drop_index(
        "ix_market_session_job_revision",
        table_name="market_session_job",
        schema="operation",
    )
    op.drop_index(
        "ix_market_session_job_exchange_date",
        table_name="market_session_job",
        schema="operation",
    )
    op.drop_index(
        "ix_market_session_job_claim_expires",
        table_name="market_session_job",
        schema="operation",
    )
    op.drop_index(
        "ix_market_session_job_due",
        table_name="market_session_job",
        schema="operation",
    )
    op.drop_table("market_session_job", schema="operation")
