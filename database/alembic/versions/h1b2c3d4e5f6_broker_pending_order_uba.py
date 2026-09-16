"""STEP 8-5-20 — broker_pending_order UBA identity.

Revision ID: h1b2c3d4e5f6
Revises: g0a1b2c3d4e5
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "g0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "broker_pending_order",
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "broker_pending_order",
        sa.Column("masked_account_ref", sa.String(40), nullable=True),
        schema="trading",
    )

    # 기존 행(있을 경우): UBA 미확정 → LEGACY — 운영 조회는 UBA 경로만
    op.execute(
        """
        UPDATE trading.broker_pending_order
        SET masked_account_ref = CASE
              WHEN length(account_number) > 4
              THEN repeat('*', greatest(length(account_number) - 4, 0))
                   || right(account_number, 4)
              ELSE '****'
            END
        WHERE masked_account_ref IS NULL
        """
    )

    op.drop_constraint(
        "uq_broker_pending_order_number",
        "broker_pending_order",
        schema="trading",
        type_="unique",
    )

    # account_number 단독 Unique 금지 — UBA + broker_order_id
    op.create_index(
        "uq_broker_pending_order_uba_order",
        "broker_pending_order",
        ["broker_code", "user_broker_account_id", "broker_order_id"],
        unique=True,
        schema="trading",
        postgresql_where=sa.text("user_broker_account_id IS NOT NULL"),
    )
    op.create_index(
        "ix_broker_pending_order_uba",
        "broker_pending_order",
        ["user_broker_account_id"],
        schema="trading",
    )
    # 테이블 비어 있음(0행) 전제 — UBA 필수화
    op.execute(
        """
        DELETE FROM trading.broker_pending_order
        WHERE user_broker_account_id IS NULL
        """
    )
    op.alter_column(
        "broker_pending_order",
        "user_broker_account_id",
        schema="trading",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_broker_pending_order_uba",
        "broker_pending_order",
        "user_broker_account",
        ["user_broker_account_id"],
        ["user_broker_account_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="RESTRICT",
    )

    # 원문 계좌번호 컬럼 → 내부 식별 금지 (신규 저장은 UBA:{id} 토큰)
    op.alter_column(
        "broker_pending_order",
        "account_number",
        schema="trading",
        existing_type=sa.String(30),
        nullable=False,
        comment="legacy/broker display token — not internal identity",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_broker_pending_order_uba",
        "broker_pending_order",
        schema="trading",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_broker_pending_order_uba",
        table_name="broker_pending_order",
        schema="trading",
    )
    op.drop_index(
        "uq_broker_pending_order_uba_order",
        table_name="broker_pending_order",
        schema="trading",
    )
    op.create_unique_constraint(
        "uq_broker_pending_order_number",
        "broker_pending_order",
        ["broker_code", "account_number", "broker_order_id"],
        schema="trading",
    )
    op.drop_column(
        "broker_pending_order", "masked_account_ref", schema="trading"
    )
    op.drop_column(
        "broker_pending_order", "user_broker_account_id", schema="trading"
    )
