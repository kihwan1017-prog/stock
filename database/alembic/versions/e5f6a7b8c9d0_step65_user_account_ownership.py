"""STEP65 — Paper 기본계좌 플래그 + 회원별 Broker 연결

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Paper: 기본/활성 플래그
    op.add_column(
        "paper_account",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="trading",
    )
    op.add_column(
        "paper_account",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="trading",
    )

    # 사용자당 가장 작은 account_id 를 기본 계좌로 백필
    op.execute(
        """
        UPDATE trading.paper_account AS pa
        SET is_default = TRUE
        FROM (
            SELECT user_id, MIN(account_id) AS account_id
            FROM trading.paper_account
            WHERE user_id IS NOT NULL
            GROUP BY user_id
        ) AS primary_row
        WHERE pa.account_id = primary_row.account_id
        """
    )

    # 사용자당 기본 Paper 계좌 1개 보장 (partial unique)
    op.execute(
        """
        CREATE UNIQUE INDEX uq_paper_account_user_default
        ON trading.paper_account (user_id)
        WHERE is_default IS TRUE AND user_id IS NOT NULL
        """
    )

    # 회원별 Broker 계좌 연결 (평문 계좌번호/시크릿 저장 금지)
    op.create_table(
        "user_broker_account",
        sa.Column(
            "user_broker_account_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("broker_code", sa.String(length=20), nullable=False),
        sa.Column("account_alias", sa.String(length=100), nullable=False),
        sa.Column("account_ref_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "masked_account_number",
            sa.String(length=40),
            nullable=True,
        ),
        sa.Column(
            "currency_code",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'KRW'"),
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "connection_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'DISCONNECTED'"),
        ),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
            ["user_id"],
            ["auth.user.user_id"],
            name="fk_user_broker_account_user",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "broker_code",
            "account_ref_hash",
            name="uq_user_broker_account_ref",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_user_broker_account_user_id",
        "user_broker_account",
        ["user_id"],
        schema="trading",
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_user_broker_account_user_default
        ON trading.user_broker_account (user_id, broker_code)
        WHERE is_default IS TRUE AND is_active IS TRUE
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS trading.uq_user_broker_account_user_default")
    op.drop_index(
        "ix_user_broker_account_user_id",
        table_name="user_broker_account",
        schema="trading",
    )
    op.drop_table("user_broker_account", schema="trading")
    op.execute("DROP INDEX IF EXISTS trading.uq_paper_account_user_default")
    op.drop_column("paper_account", "is_active", schema="trading")
    op.drop_column("paper_account", "is_default", schema="trading")
