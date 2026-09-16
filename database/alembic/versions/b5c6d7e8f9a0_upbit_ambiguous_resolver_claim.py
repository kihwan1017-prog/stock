"""STEP 8-5-14 — Upbit Ambiguous Resolver Scheduler: DB Claim + Run History.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9

Remote 조회 전용 스케줄러를 위한 원자적 Claim 컬럼과 실행 이력 테이블을
추가한다. 주문 재제출 로직은 이 Migration과 무관하다 (여전히 auto_resubmit=false).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Claim 컬럼 ---------------------------------------------------
    op.add_column(
        "trading_order",
        sa.Column("resolver_claimed_by", sa.String(100), nullable=True),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "resolver_claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "resolver_claim_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column("resolver_run_token", sa.String(64), nullable=True),
        schema="trading",
    )

    op.create_index(
        "ix_trading_order_resolver_due",
        "trading_order",
        ["broker_code", "status_code", "next_remote_lookup_at"],
        schema="trading",
    )
    op.create_index(
        "ix_trading_order_resolver_claim_expires",
        "trading_order",
        ["resolver_claim_expires_at"],
        schema="trading",
    )
    op.create_index(
        "ix_trading_order_uba_next_lookup",
        "trading_order",
        ["user_broker_account_id", "next_remote_lookup_at"],
        schema="trading",
    )

    # -- Backfill ------------------------------------------------------
    # 1) Identifier가 있는 AMBIGUOUS_SUBMISSION/REMOTE_LOOKUP_PENDING 중
    #    next_remote_lookup_at 이 비어 있는 건 — 즉시 조회 대상이 되도록
    #    ambiguous_since(or updated_at/now) + 2초 로 설정한다.
    backfilled_due = op.get_bind().execute(
        sa.text(
            """
            WITH updated AS (
                UPDATE trading.trading_order
                SET next_remote_lookup_at =
                    COALESCE(ambiguous_since, updated_at, NOW())
                    + INTERVAL '2 seconds'
                WHERE status_code IN (
                    'AMBIGUOUS_SUBMISSION', 'REMOTE_LOOKUP_PENDING'
                )
                  AND next_remote_lookup_at IS NULL
                  AND client_order_identifier IS NOT NULL
                  AND client_order_identifier <> ''
                RETURNING order_id
            )
            SELECT count(*) FROM updated
            """
        )
    ).scalar()

    # 2) Identifier가 없는 건 — 원격 조회가 불가능하므로 Due 대기열에서
    #    제외하고 MANUAL_REVIEW_REQUIRED 로 전환한다 (자동 재제출 없음).
    backfilled_manual = op.get_bind().execute(
        sa.text(
            """
            WITH updated AS (
                UPDATE trading.trading_order
                SET status_code = 'MANUAL_REVIEW_REQUIRED',
                    ambiguity_reason = COALESCE(
                        ambiguity_reason, 'NO_IDENTIFIER_BACKFILL'
                    )
                WHERE status_code IN (
                    'AMBIGUOUS_SUBMISSION', 'REMOTE_LOOKUP_PENDING'
                )
                  AND (
                    client_order_identifier IS NULL
                    OR client_order_identifier = ''
                  )
                RETURNING order_id
            )
            SELECT count(*) FROM updated
            """
        )
    ).scalar()

    # STEP 8-5-14 Backfill 결과 — 운영 Migration 로그에서 확인 가능하도록 고지.
    # (개발 환경에서는 대상이 0건일 수 있음)
    print(
        "[STEP 8-5-14] backfill: "
        f"due_scheduled={backfilled_due or 0}, "
        f"manual_review_no_identifier={backfilled_manual or 0}"
    )

    # -- 실행 이력 테이블 ------------------------------------------------
    op.create_table(
        "upbit_ambiguous_resolution_run",
        sa.Column(
            "upbit_ambiguous_resolution_run_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column(
            "trigger_type",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'SCHEDULER'"),
        ),
        sa.Column("requested_by", sa.String(150), nullable=True),
        sa.Column("instance_id", sa.String(200), nullable=True),
        sa.Column(
            "status_code",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'RUNNING'"),
        ),
        sa.Column(
            "due_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "claimed_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "found_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "not_found_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "manual_review_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "conflict_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "lock_busy_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "credential_blocked_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "rate_limited_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "error_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "result_summary",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "finished_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_upbit_ambiguous_resolution_run_started",
        "upbit_ambiguous_resolution_run",
        ["started_at"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_ambiguous_resolution_run_status",
        "upbit_ambiguous_resolution_run",
        ["status_code"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_upbit_ambiguous_resolution_run_status",
        table_name="upbit_ambiguous_resolution_run",
        schema="operation",
    )
    op.drop_index(
        "ix_upbit_ambiguous_resolution_run_started",
        table_name="upbit_ambiguous_resolution_run",
        schema="operation",
    )
    op.drop_table("upbit_ambiguous_resolution_run", schema="operation")

    op.drop_index(
        "ix_trading_order_uba_next_lookup",
        table_name="trading_order",
        schema="trading",
    )
    op.drop_index(
        "ix_trading_order_resolver_claim_expires",
        table_name="trading_order",
        schema="trading",
    )
    op.drop_index(
        "ix_trading_order_resolver_due",
        table_name="trading_order",
        schema="trading",
    )
    for col in (
        "resolver_run_token",
        "resolver_claim_expires_at",
        "resolver_claimed_at",
        "resolver_claimed_by",
    ):
        op.drop_column("trading_order", col, schema="trading")
