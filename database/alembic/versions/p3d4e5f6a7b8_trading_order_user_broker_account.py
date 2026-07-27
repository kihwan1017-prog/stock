"""trading_order에 UserBrokerAccount FK 추가 (STEP 8-1)

Revision ID: p3d4e5f6a7b8
Revises: o2c3d4e5f6a7
Create Date: 2026-07-23

정책:
- trading.trading_order.user_broker_account_id (nullable FK)
- Paper 주문은 기존 account_id 유지, UBA는 NULL
- LIVE 키움·업비트 주문은 애플리케이션에서 UBA 필수
- Backfill: paper_account.user_id + broker_code 가 일치하는
  UBA가 정확히 1개인 경우만 자동 연결 (애매하면 연결하지 않음)
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "o2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "trading_order",
        sa.Column(
            "user_broker_account_id",
            sa.BigInteger(),
            nullable=True,
        ),
        schema="trading",
    )
    op.create_foreign_key(
        "fk_trading_order_user_broker_account",
        "trading_order",
        "user_broker_account",
        ["user_broker_account_id"],
        ["user_broker_account_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_trading_order_user_broker_account_id",
        "trading_order",
        ["user_broker_account_id"],
        unique=False,
        schema="trading",
    )
    op.create_index(
        "ix_trading_order_uba_status",
        "trading_order",
        ["user_broker_account_id", "status_code"],
        unique=False,
        schema="trading",
    )
    # 계좌별 외부 주문번호 유일성 (둘 다 있을 때만)
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_trading_order_uba_broker_order_id
            ON trading.trading_order (user_broker_account_id, broker_order_id)
            WHERE user_broker_account_id IS NOT NULL
              AND broker_order_id IS NOT NULL
            """
        )
    )

    bind = op.get_bind()
    target = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)::int
            FROM trading.trading_order
            WHERE upper(broker_code) IN ('KIWOOM', 'UPBIT')
              AND user_broker_account_id IS NULL
            """
        )
    ).scalar() or 0

    # 우선순위: paper.user_id + broker_code 일치 UBA가 정확히 1개일 때만 연결
    linked = bind.execute(
        sa.text(
            """
            WITH match_counts AS (
                SELECT
                    o.order_id,
                    COUNT(uba.user_broker_account_id) AS uba_count
                FROM trading.trading_order o
                INNER JOIN trading.paper_account pa
                    ON pa.account_id = o.account_id
                LEFT JOIN trading.user_broker_account uba
                    ON uba.user_id = pa.user_id
                   AND upper(uba.broker_code) = upper(o.broker_code)
                WHERE o.user_broker_account_id IS NULL
                  AND upper(o.broker_code) IN ('KIWOOM', 'UPBIT')
                  AND pa.user_id IS NOT NULL
                GROUP BY o.order_id
            ),
            unambiguous AS (
                SELECT
                    o.order_id,
                    uba.user_broker_account_id
                FROM trading.trading_order o
                INNER JOIN trading.paper_account pa
                    ON pa.account_id = o.account_id
                INNER JOIN trading.user_broker_account uba
                    ON uba.user_id = pa.user_id
                   AND upper(uba.broker_code) = upper(o.broker_code)
                INNER JOIN match_counts mc
                    ON mc.order_id = o.order_id
                   AND mc.uba_count = 1
                WHERE o.user_broker_account_id IS NULL
                  AND upper(o.broker_code) IN ('KIWOOM', 'UPBIT')
            )
            UPDATE trading.trading_order AS o
            SET user_broker_account_id = u.user_broker_account_id
            FROM unambiguous AS u
            WHERE o.order_id = u.order_id
            """
        )
    )
    success = int(linked.rowcount or 0)

    remaining = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)::int
            FROM trading.trading_order
            WHERE upper(broker_code) IN ('KIWOOM', 'UPBIT')
              AND user_broker_account_id IS NULL
            """
        )
    ).scalar() or 0

    # 운영 확인용 요약 (임의 계좌 연결 금지 — 실패분은 NULL 유지)
    print(
        "STEP8-1 backfill: "
        f"target={target}, success={success}, unlinkable={remaining}"
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_trading_order_uba_broker_order_id"
        )
    )
    op.drop_index(
        "ix_trading_order_uba_status",
        table_name="trading_order",
        schema="trading",
    )
    op.drop_index(
        "ix_trading_order_user_broker_account_id",
        table_name="trading_order",
        schema="trading",
    )
    op.drop_constraint(
        "fk_trading_order_user_broker_account",
        "trading_order",
        schema="trading",
        type_="foreignkey",
    )
    op.drop_column(
        "trading_order",
        "user_broker_account_id",
        schema="trading",
    )
