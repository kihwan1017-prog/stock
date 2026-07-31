"""STEP 2-5-2 — trading_order.account_id FK to paper_account (NOT VALID)

Revision ID: 2fab1d256681
Revises: dac603609696
Create Date: 2026-07-28

Scope (STEP 2-5-2 only):
1. trading.trading_order.account_id -> trading.paper_account.account_id
   FK 추가, ondelete=RESTRICT
2. 컬럼 자체(타입/nullable)는 변경하지 않는다.
3. 기존 인덱스(ix_trading_order_account_status)는 유지, 신규 인덱스 없음.

Orphan 데이터 안내 (STEP 2-5-2B 조사 결과):
  실행 시점 기준 trading.trading_order에 order_id=250 (account_id=58) 1건이
  trading.paper_account를 참조하지 못하는 orphan으로 확인됨. 조사 결과 이
  값(58)은 동일 행의 user_broker_account_id와 동일하며, STEP9-6 라이브
  스모크 테스트(actor=STEP9_6_OPERATOR/STEP9_6_RECONCILE, 실제 Upbit
  체결 완료 FILLED 주문)로 생성된 것으로 확인됐다. 이 주문에 대응하는
  paper_account가 애초에 존재하지 않아(user_id=7 소유 paper_account 없음)
  객관적 근거로 확정할 수 있는 백필 대상이 없다.

  원칙(STEP 2-5-2 지시)에 따라:
    - orphan 주문을 삭제하지 않는다.
    - 임의 계좌(MIN 등)로 백필하지 않는다.
    - 원인 미확인 상태에서 VALIDATE CONSTRAINT를 강행하지 않는다.

  따라서 이 마이그레이션은 FK를 NOT VALID로만 추가한다:
    - 기존 orphan 행은 그대로 유지(데이터 손실 없음).
    - 신규 INSERT/UPDATE는 이 시점부터 FK로 즉시 강제된다(주 목적 달성).
    - VALIDATE CONSTRAINT는 이 마이그레이션에서 실행하지 않는다. order_id=250
      의 처리 방침(회고적 paper_account 생성 등 운영/비즈니스 결정)이
      확정된 뒤 별도 마이그레이션으로 VALIDATE를 수행해야 한다.

Settlement/Ledger FK, UserBrokerAccount 관련 변경은 이 마이그레이션에
포함하지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2fab1d256681"
down_revision: Union[str, Sequence[str], None] = "dac603609696"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT_NAME = "fk_trading_order_account"


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 기존 Constraint 존재 여부 방어
    existing = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'trading'
              AND t.relname = 'trading_order'
              AND c.conname = :name
            """
        ),
        {"name": _CONSTRAINT_NAME},
    ).fetchone()
    if existing is not None:
        raise RuntimeError(
            f"upgrade 중단: 제약 {_CONSTRAINT_NAME}이(가) 이미 "
            "trading.trading_order에 존재합니다. 마이그레이션 상태를 "
            "확인하세요(중복 실행 방지)."
        )

    # 2)+3)+4) ADD CONSTRAINT ... FOREIGN KEY ... REFERENCES ... ON DELETE
    #    RESTRICT ... NOT VALID — 기존 orphan(order_id=250) 때문에 전체
    #    검증은 보류하고, 신규/변경 행부터 강제한다.
    op.execute(
        sa.text(
            """
            ALTER TABLE trading.trading_order
            ADD CONSTRAINT fk_trading_order_account
            FOREIGN KEY (account_id)
            REFERENCES trading.paper_account (account_id)
            ON DELETE RESTRICT
            NOT VALID
            """
        )
    )

    # 5)+6) VALIDATE CONSTRAINT는 의도적으로 실행하지 않는다.
    # (미해소 orphan order_id=250 — 위 상단 설명 참고. 운영 판단 후 별도
    #  마이그레이션에서 `ALTER TABLE trading.trading_order
    #  VALIDATE CONSTRAINT fk_trading_order_account;` 실행 권장)


def downgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "trading_order",
        schema="trading",
        type_="foreignkey",
    )
