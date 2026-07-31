"""STEP 2-5-3 — Settlement/Ledger 계좌 FK 보강

Revision ID: 84b4b4a8c996
Revises: 2fab1d256681
Create Date: 2026-07-28

Scope (STEP 2-5-3 only):
  trading.account_daily_settlement.user_broker_account_id
    -> trading.user_broker_account.user_broker_account_id (RESTRICT)
  trading.account_daily_settlement.paper_account_id
    -> trading.paper_account.account_id (RESTRICT)
  trading.ledger_adjustment.user_broker_account_id
    -> trading.user_broker_account.user_broker_account_id (RESTRICT)
  trading.ledger_adjustment.paper_account_id
    -> trading.paper_account.account_id (RESTRICT)

XOR CheckConstraint(ck_account_daily_settlement_account_xor,
ck_ledger_adjustment_account_xor)는 그대로 유지하며 이 마이그레이션에서
건드리지 않는다. 컬럼 타입/nullable도 변경하지 않는다.

Orphan 사전 점검 (STEP 2-5-3B, 로컬 dev DB 스냅샷 기준):
  account_daily_settlement 전체 0행, ledger_adjustment 전체 0행.
  두 테이블 모두 UBA/PaperAccount orphan 0건, XOR 위반(둘 다 NULL 또는
  둘 다 NOT NULL) 0건. 이에 따라 네 FK 모두 NOT VALID로 추가한 뒤
  같은 마이그레이션 내에서 VALIDATE CONSTRAINT까지 수행한다(0행이라
  VALIDATE 비용도 사실상 없음).

  단, 이 점검은 이 마이그레이션을 실행하는 로컬 dev DB의 데이터 스냅샷
  기준이다. 다른 환경(스테이징/운영 등)에 이 마이그레이션을 적용하기
  전에는 반드시 동일한 orphan 점검 쿼리를 그 환경에서 재실행해야 한다.
  만약 orphan이 발견되면 이 마이그레이션을 그대로 적용해서는 안 되며,
  STEP 2-5-2(trading_order FK)에서 사용한 NOT VALID 전용 패턴을
  참고해 별도 처리가 필요하다.

TradingOrder(fk_trading_order_account)는 이 마이그레이션에서 다루지
않으며 STEP 2-5-2가 남긴 NOT VALID 상태를 그대로 둔다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "84b4b4a8c996"
down_revision: Union[str, Sequence[str], None] = "2fab1d256681"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FKS = (
    # (constraint_name, table, column, referred_table, referred_column)
    (
        "fk_account_daily_settlement_uba",
        "account_daily_settlement",
        "user_broker_account_id",
        "user_broker_account",
        "user_broker_account_id",
    ),
    (
        "fk_account_daily_settlement_paper_account",
        "account_daily_settlement",
        "paper_account_id",
        "paper_account",
        "account_id",
    ),
    (
        "fk_ledger_adjustment_uba",
        "ledger_adjustment",
        "user_broker_account_id",
        "user_broker_account",
        "user_broker_account_id",
    ),
    (
        "fk_ledger_adjustment_paper_account",
        "ledger_adjustment",
        "paper_account_id",
        "paper_account",
        "account_id",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()

    for name, table, column, ref_table, ref_column in _FKS:
        # 1) 기존 Constraint 존재 여부 방어
        existing = bind.execute(
            sa.text(
                """
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'trading'
                  AND t.relname = :table
                  AND c.conname = :name
                """
            ),
            {"table": table, "name": name},
        ).fetchone()
        if existing is not None:
            raise RuntimeError(
                f"upgrade 중단: 제약 {name}이(가) 이미 trading.{table}에 "
                "존재합니다. 마이그레이션 상태를 확인하세요(중복 실행 방지)."
            )

        # 2) ADD CONSTRAINT ... NOT VALID
        op.execute(
            sa.text(
                f"""
                ALTER TABLE trading.{table}
                ADD CONSTRAINT {name}
                FOREIGN KEY ({column})
                REFERENCES trading.{ref_table} ({ref_column})
                ON DELETE RESTRICT
                NOT VALID
                """
            )
        )

        # 3) orphan 0건(사전 점검 완료) — 같은 마이그레이션에서 즉시 VALIDATE
        op.execute(
            sa.text(
                f"""
                ALTER TABLE trading.{table}
                VALIDATE CONSTRAINT {name}
                """
            )
        )


def downgrade() -> None:
    for name, table, _column, _ref_table, _ref_column in reversed(_FKS):
        op.drop_constraint(
            name,
            table,
            schema="trading",
            type_="foreignkey",
        )
