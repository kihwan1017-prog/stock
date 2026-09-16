"""STEP 8-5-16 — EOD Account Settlement tables.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_daily_settlement",
        sa.Column(
            "settlement_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("paper_account_id", sa.BigInteger(), nullable=True),
        sa.Column("broker_code", sa.String(30), nullable=False),
        sa.Column("market_date", sa.Date(), nullable=False),
        sa.Column("calendar_revision", sa.Integer(), nullable=True),
        sa.Column("settlement_type", sa.String(40), nullable=False),
        sa.Column(
            "status_code",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_sync_status", sa.String(40), nullable=True),
        sa.Column("order_reconciliation_status", sa.String(40), nullable=True),
        sa.Column(
            "execution_reconciliation_status", sa.String(40), nullable=True
        ),
        sa.Column(
            "position_reconciliation_status", sa.String(40), nullable=True
        ),
        sa.Column("cash_reconciliation_status", sa.String(40), nullable=True),
        sa.Column("pnl_calculation_status", sa.String(40), nullable=True),
        sa.Column(
            "open_order_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unresolved_order_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "position_mismatch_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cash_mismatch_amount",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "realized_pnl",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unrealized_pnl",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "gross_pnl",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "fees",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "taxes",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "net_pnl",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("opening_equity", sa.Numeric(20, 8), nullable=True),
        sa.Column("closing_equity", sa.Numeric(20, 8), nullable=True),
        sa.Column("external_equity", sa.Numeric(20, 8), nullable=True),
        sa.Column("internal_equity", sa.Numeric(20, 8), nullable=True),
        sa.Column("equity_difference", sa.Numeric(20, 8), nullable=True),
        sa.Column("result_code", sa.String(80), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "external_snapshot_meta",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "detail_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
        sa.CheckConstraint(
            "(user_broker_account_id IS NOT NULL AND paper_account_id IS NULL)"
            " OR (user_broker_account_id IS NULL AND paper_account_id IS NOT NULL)",
            name="ck_account_daily_settlement_account_xor",
        ),
        sa.CheckConstraint(
            "retry_count >= 0",
            name="ck_account_daily_settlement_retry_nonneg",
        ),
        sa.CheckConstraint(
            "open_order_count >= 0 AND unresolved_order_count >= 0"
            " AND position_mismatch_count >= 0",
            name="ck_account_daily_settlement_counts_nonneg",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_account_daily_settlement_date_status",
        "account_daily_settlement",
        ["market_date", "status_code"],
        schema="trading",
    )
    op.create_index(
        "ix_account_daily_settlement_broker_date",
        "account_daily_settlement",
        ["broker_code", "market_date"],
        schema="trading",
    )
    # Partial Unique — NULL 계좌 컬럼 중복 허용 방지
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_account_daily_settlement_uba_date_type
            ON trading.account_daily_settlement (
                user_broker_account_id, market_date, settlement_type
            )
            WHERE user_broker_account_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_account_daily_settlement_paper_date_type
            ON trading.account_daily_settlement (
                paper_account_id, market_date, settlement_type
            )
            WHERE paper_account_id IS NOT NULL
            """
        )
    )

    op.create_table(
        "account_daily_settlement_issue",
        sa.Column(
            "issue_id", sa.BigInteger(), sa.Identity(), primary_key=True
        ),
        sa.Column("settlement_id", sa.BigInteger(), nullable=False),
        sa.Column("issue_type", sa.String(80), nullable=False),
        sa.Column(
            "severity",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'CRITICAL'"),
        ),
        sa.Column("symbol", sa.String(40), nullable=True),
        sa.Column("local_value", sa.Text(), nullable=True),
        sa.Column("external_value", sa.Text(), nullable=True),
        sa.Column("difference", sa.Text(), nullable=True),
        sa.Column("tolerance", sa.Text(), nullable=True),
        sa.Column("result_code", sa.String(80), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "resolved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("resolved_by", sa.String(150), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["settlement_id"],
            ["trading.account_daily_settlement.settlement_id"],
            name="fk_settlement_issue_settlement",
            ondelete="CASCADE",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_account_daily_settlement_issue_settlement",
        "account_daily_settlement_issue",
        ["settlement_id", "issue_type"],
        schema="trading",
    )
    op.create_index(
        "ix_account_daily_settlement_issue_unresolved",
        "account_daily_settlement_issue",
        ["resolved", "severity"],
        schema="trading",
    )

    op.create_table(
        "ledger_adjustment",
        sa.Column(
            "ledger_adjustment_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("paper_account_id", sa.BigInteger(), nullable=True),
        sa.Column("market_date", sa.Date(), nullable=True),
        sa.Column("asset_code", sa.String(40), nullable=False),
        sa.Column("adjustment_type", sa.String(40), nullable=False),
        sa.Column("before_value", sa.Text(), nullable=True),
        sa.Column("adjustment_value", sa.Text(), nullable=True),
        sa.Column("after_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(150), nullable=False),
        sa.Column("approved_by", sa.String(150), nullable=True),
        sa.Column(
            "status_code",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'REQUESTED'"),
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "(user_broker_account_id IS NOT NULL AND paper_account_id IS NULL)"
            " OR (user_broker_account_id IS NULL AND paper_account_id IS NOT NULL)",
            name="ck_ledger_adjustment_account_xor",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_ledger_adjustment_status",
        "ledger_adjustment",
        ["status_code"],
        schema="trading",
    )

    # 과거 가짜 Settlement 생성 금지
    print("[STEP 8-5-16] backfill: none (past settlements not invented)")


def downgrade() -> None:
    op.drop_index(
        "ix_ledger_adjustment_status",
        table_name="ledger_adjustment",
        schema="trading",
    )
    op.drop_table("ledger_adjustment", schema="trading")
    op.drop_index(
        "ix_account_daily_settlement_issue_unresolved",
        table_name="account_daily_settlement_issue",
        schema="trading",
    )
    op.drop_index(
        "ix_account_daily_settlement_issue_settlement",
        table_name="account_daily_settlement_issue",
        schema="trading",
    )
    op.drop_table("account_daily_settlement_issue", schema="trading")
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_account_daily_settlement_uba_date_type"
        )
    )
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_account_daily_settlement_paper_date_type"
        )
    )
    op.drop_index(
        "ix_account_daily_settlement_broker_date",
        table_name="account_daily_settlement",
        schema="trading",
    )
    op.drop_index(
        "ix_account_daily_settlement_date_status",
        table_name="account_daily_settlement",
        schema="trading",
    )
    op.drop_table("account_daily_settlement", schema="trading")
