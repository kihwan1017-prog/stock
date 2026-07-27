"""STEP 8-5-4 — Upbit remote-only recovery conflict table.

Revision ID: v9c0d1e2f3a4
Revises: u8b9c0d1e2f3
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "u8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACTIVE_REVIEW = (
    "PENDING_REVIEW",
    "ON_HOLD",
)


def upgrade() -> None:
    op.create_table(
        "broker_recovery_conflict",
        sa.Column(
            "broker_recovery_conflict_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("broker_recovery_run_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("paper_account_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "broker_code",
            sa.String(30),
            nullable=False,
            server_default="UPBIT",
        ),
        sa.Column(
            "conflict_type",
            sa.String(60),
            nullable=False,
            server_default="REMOTE_ORDER_NOT_FOUND_LOCALLY",
        ),
        sa.Column("external_order_id", sa.String(100), nullable=False),
        sa.Column("external_order_id_masked", sa.String(40), nullable=True),
        sa.Column("market_code", sa.String(40), nullable=True),
        sa.Column("side_code", sa.String(10), nullable=True),
        sa.Column("order_type_code", sa.String(30), nullable=True),
        sa.Column("external_status", sa.String(40), nullable=True),
        sa.Column(
            "requested_quantity",
            sa.Numeric(28, 8),
            nullable=True,
        ),
        sa.Column(
            "executed_quantity",
            sa.Numeric(28, 8),
            nullable=True,
        ),
        sa.Column(
            "remaining_quantity",
            sa.Numeric(28, 8),
            nullable=True,
        ),
        sa.Column("order_price", sa.Numeric(20, 8), nullable=True),
        sa.Column(
            "average_execution_price",
            sa.Numeric(20, 8),
            nullable=True,
        ),
        sa.Column("paid_fee", sa.Numeric(24, 8), nullable=True),
        sa.Column(
            "external_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "review_status",
            sa.String(40),
            nullable=False,
            server_default="PENDING_REVIEW",
        ),
        sa.Column(
            "risk_level",
            sa.String(20),
            nullable=False,
            server_default="HIGH",
        ),
        sa.Column("resolution_type", sa.String(60), nullable=True),
        sa.Column("resolved_by", sa.String(100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("linked_internal_order_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "last_remote_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "remote_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "pause_reason",
            sa.String(80),
            nullable=True,
            server_default="UPBIT_REMOTE_ONLY_ORDER_REVIEW",
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
            ["broker_recovery_run_id"],
            ["operation.broker_recovery_run.broker_recovery_run_id"],
            name="fk_recovery_conflict_run",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_broker_account_id"],
            ["trading.user_broker_account.user_broker_account_id"],
            name="fk_recovery_conflict_uba",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linked_internal_order_id"],
            ["trading.trading_order.order_id"],
            name="fk_recovery_conflict_order",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "broker_code IN ('UPBIT','KIWOOM')",
            name="ck_recovery_conflict_broker",
        ),
        sa.CheckConstraint(
            "conflict_type IN ("
            "'REMOTE_ORDER_NOT_FOUND_LOCALLY',"
            "'ORDER_ACCOUNT_MISMATCH',"
            "'ORDER_MARKET_MISMATCH',"
            "'ORDER_QUANTITY_MISMATCH',"
            "'EXECUTION_MISMATCH',"
            "'BALANCE_MISMATCH',"
            "'UNKNOWN_REMOTE_ORDER'"
            ")",
            name="ck_recovery_conflict_type",
        ),
        sa.CheckConstraint(
            "review_status IN ("
            "'PENDING_REVIEW',"
            "'APPROVED_IMPORT',"
            "'IGNORED',"
            "'ON_HOLD',"
            "'REJECTED',"
            "'RESOLVED',"
            "'REMOTE_DISAPPEARED'"
            ")",
            name="ck_recovery_conflict_review",
        ),
        sa.CheckConstraint(
            "risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_recovery_conflict_risk",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_recovery_conflict_review",
        "broker_recovery_conflict",
        ["review_status", "broker_code"],
        schema="operation",
    )
    op.create_index(
        "ix_recovery_conflict_uba",
        "broker_recovery_conflict",
        ["user_broker_account_id"],
        schema="operation",
    )
    op.create_index(
        "ix_recovery_conflict_external",
        "broker_recovery_conflict",
        ["broker_code", "external_order_id"],
        schema="operation",
    )
    # 활성 검토 상태에서는 UUID당 Conflict 1개
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_recovery_conflict_active_external
            ON operation.broker_recovery_conflict (
                broker_code,
                COALESCE(user_broker_account_id, 0),
                external_order_id
            )
            WHERE review_status IN ('PENDING_REVIEW', 'ON_HOLD')
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS "
            "operation.uq_recovery_conflict_active_external"
        )
    )
    op.drop_index(
        "ix_recovery_conflict_external",
        table_name="broker_recovery_conflict",
        schema="operation",
    )
    op.drop_index(
        "ix_recovery_conflict_uba",
        table_name="broker_recovery_conflict",
        schema="operation",
    )
    op.drop_index(
        "ix_recovery_conflict_review",
        table_name="broker_recovery_conflict",
        schema="operation",
    )
    op.drop_table("broker_recovery_conflict", schema="operation")
