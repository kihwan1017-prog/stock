"""STEP 8-4 Alembic — Recovery 계좌 상태·실행 이력 확장.

Revision ID: s6f7a8b9c0d1
Revises: r5e6f7a8b9c0
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "r5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 기존 run 테이블에 계좌·트리거 메타 추가 (기존 행 보존)
    op.add_column(
        "broker_recovery_run",
        sa.Column("trigger_type", sa.String(30), server_default="MANUAL"),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column("broker_code", sa.String(30), nullable=True),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column("paper_account_id", sa.BigInteger(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column(
            "user_broker_account_id", sa.BigInteger(), nullable=True
        ),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column("requested_by", sa.String(100), nullable=True),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column(
            "open_orders_checked",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column(
            "orders_updated",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column(
            "fills_created",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column(
            "balances_updated",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column(
            "positions_updated",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        schema="operation",
    )
    op.add_column(
        "broker_recovery_run",
        sa.Column(
            "conflicts_found",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        schema="operation",
    )
    op.create_index(
        "ix_broker_recovery_run_broker_started",
        "broker_recovery_run",
        ["broker_code", "started_at"],
        schema="operation",
    )

    op.create_table(
        "broker_recovery_account_state",
        sa.Column(
            "recovery_account_state_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("broker_code", sa.String(30), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("paper_account_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "user_broker_account_id", sa.BigInteger(), nullable=True
        ),
        sa.Column(
            "recovery_status",
            sa.String(30),
            nullable=False,
            server_default="IDLE",
        ),
        sa.Column(
            "trading_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("lock_holder", sa.String(100), nullable=True),
        sa.Column(
            "lock_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_recovery_run_id", sa.BigInteger(), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["paper_account_id"],
            ["trading.paper_account.account_id"],
            name="fk_recovery_state_paper",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_broker_account_id"],
            ["trading.user_broker_account.user_broker_account_id"],
            name="fk_recovery_state_uba",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_recovery_run_id"],
            ["operation.broker_recovery_run.broker_recovery_run_id"],
            name="fk_recovery_state_run",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "recovery_status IN ("
            "'IDLE','RUNNING','FAILED','MANUAL_REVIEW','SUCCESS')",
            name="ck_recovery_account_status",
        ),
        schema="operation",
    )
    # Paper 계좌 unique
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_recovery_state_paper
            ON operation.broker_recovery_account_state (
                broker_code, paper_account_id
            )
            WHERE paper_account_id IS NOT NULL
            """
        )
    )
    # UBA unique
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_recovery_state_uba
            ON operation.broker_recovery_account_state (
                broker_code, user_broker_account_id
            )
            WHERE user_broker_account_id IS NOT NULL
            """
        )
    )
    # 시스템(환경변수) 키움 단일 슬롯
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_recovery_state_system_kiwoom
            ON operation.broker_recovery_account_state (broker_code)
            WHERE paper_account_id IS NULL
              AND user_broker_account_id IS NULL
              AND broker_code = 'KIWOOM'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DROP INDEX IF EXISTS operation.uq_recovery_state_system_kiwoom")
    )
    op.execute(
        sa.text("DROP INDEX IF EXISTS operation.uq_recovery_state_uba")
    )
    op.execute(
        sa.text("DROP INDEX IF EXISTS operation.uq_recovery_state_paper")
    )
    op.drop_table("broker_recovery_account_state", schema="operation")
    op.drop_index(
        "ix_broker_recovery_run_broker_started",
        table_name="broker_recovery_run",
        schema="operation",
    )
    for col in (
        "conflicts_found",
        "positions_updated",
        "balances_updated",
        "fills_created",
        "orders_updated",
        "open_orders_checked",
        "requested_by",
        "user_broker_account_id",
        "paper_account_id",
        "user_id",
        "broker_code",
        "trigger_type",
    ):
        op.drop_column("broker_recovery_run", col, schema="operation")
