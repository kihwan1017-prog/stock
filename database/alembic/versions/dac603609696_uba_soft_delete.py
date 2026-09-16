"""STEP 2-5-1 — UserBrokerAccount Soft Delete (deleted_at + partial unique index)

Revision ID: dac603609696
Revises: ae5f6a7b8c9d
Create Date: 2026-07-28

Scope (STEP 2-5-1 only):
1. trading.user_broker_account.deleted_at 컬럼 추가 (nullable, index)
2. 기존 uq_user_broker_account_ref(UniqueConstraint) 제거
3. 부분 유니크 인덱스 ux_user_broker_account_ref_active
   (user_id, broker_code, account_ref_hash) WHERE deleted_at IS NULL 추가

TradingOrder FK / AccountDailySettlement FK / LedgerAdjustment FK는
이 마이그레이션에 포함하지 않는다 (STEP 2-5-2 / STEP 2-5-3에서 별도 처리).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "dac603609696"
down_revision: Union[str, Sequence[str], None] = "ae5f6a7b8c9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) deleted_at 컬럼 추가 (PaperAccount.deleted_at과 동일 패턴)
    op.add_column(
        "user_broker_account",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="trading",
    )
    op.create_index(
        "ix_trading_user_broker_account_deleted_at",
        "user_broker_account",
        ["deleted_at"],
        unique=False,
        schema="trading",
    )

    # 2) 기존 전체 UniqueConstraint 제거
    op.drop_constraint(
        "uq_user_broker_account_ref",
        "user_broker_account",
        schema="trading",
        type_="unique",
    )

    # 3) 삭제되지 않은 행에만 적용되는 부분 유니크 인덱스
    #    — 소프트 삭제된 행은 (user_id, broker_code, account_ref_hash) 중복을
    #      가져도 되며, 재연결(revive) 시 기존 행을 재사용한다.
    op.create_index(
        "ux_user_broker_account_ref_active",
        "user_broker_account",
        ["user_id", "broker_code", "account_ref_hash"],
        unique=True,
        schema="trading",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # 부분 유니크 인덱스 제거
    op.drop_index(
        "ux_user_broker_account_ref_active",
        table_name="user_broker_account",
        schema="trading",
    )

    # 전체 UniqueConstraint를 되돌리기 전에, Soft Delete 도입 이후 쌓였을 수
    # 있는 (user_id, broker_code, account_ref_hash) 중복 조합을 먼저 점검한다.
    # 중복이 있으면 sa.UniqueConstraint 재생성이 즉시 실패하므로, 여기서
    # 명확한 에러로 먼저 막아 어떤 행이 문제인지 운영자가 바로 알 수 있게 한다.
    #
    # 운영 점검 쿼리(참고용, 이 마이그레이션이 자동 실행):
    #   SELECT user_id, broker_code, account_ref_hash, COUNT(*)
    #   FROM trading.user_broker_account
    #   GROUP BY user_id, broker_code, account_ref_hash
    #   HAVING COUNT(*) > 1;
    bind = op.get_bind()
    duplicate_rows = bind.execute(
        sa.text(
            """
            SELECT user_id, broker_code, account_ref_hash, COUNT(*) AS cnt
            FROM trading.user_broker_account
            GROUP BY user_id, broker_code, account_ref_hash
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if duplicate_rows:
        raise RuntimeError(
            "downgrade 중단: trading.user_broker_account에 "
            "(user_id, broker_code, account_ref_hash) 중복 조합이 "
            f"{len(duplicate_rows)}건 존재해 기존 전체 UniqueConstraint "
            "(uq_user_broker_account_ref)를 재생성할 수 없습니다. "
            "Soft Delete로 revive되지 않은 중복 행을 먼저 정리(병합/삭제)한 "
            "뒤 downgrade를 다시 실행하세요. 중복 조합: "
            f"{[tuple(r) for r in duplicate_rows][:20]}"
        )

    op.create_unique_constraint(
        "uq_user_broker_account_ref",
        "user_broker_account",
        ["user_id", "broker_code", "account_ref_hash"],
        schema="trading",
    )

    op.drop_index(
        "ix_trading_user_broker_account_deleted_at",
        table_name="user_broker_account",
        schema="trading",
    )
    op.drop_column(
        "user_broker_account", "deleted_at", schema="trading"
    )
