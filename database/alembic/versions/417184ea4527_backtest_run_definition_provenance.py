"""STEP 12-7 — backtest_run: strategy_definition_id 연결 + idempotency_key

Revision ID: 417184ea4527
Revises: 6d736aedafc9
Create Date: 2026-07-28

승인된 Strategy Definition 기반 Backtest 실행 결과를 기존
`backtest.backtest_run`에 그대로 저장하기 위한 최소 컬럼 추가.

- strategy_definition_id: nullable FK RESTRICT ->
  trading.strategy_definition.strategy_id. 기존 MovingAverage 전용 실행
  경로(strategy_id 개념 없음)는 계속 NULL로 남아 하위 호환된다.
- idempotency_key: nullable String(64) + 부분 Unique Index(NOT NULL인
  경우만) — 동일 키 재요청 시 기존 결과를 반환하기 위한 실제 DB 제약
  (in-memory lock으로 대체하지 않음, §17). 기존 MovingAverage 실행
  경로는 이 값을 채우지 않으므로 영향 없음.

새 테이블/중복 Backtest Run 구조를 만들지 않는다 — 기존
`backtest.backtest_run`/`backtest_trade`/`backtest_equity`를 그대로
재사용한다. definition_version/definition_hash/executable_hash/
compiler_version/runtime_input_hash 등 나머지 Provenance는 기존
`parameters`(JSONB) 컬럼에 담아 추가 컬럼을 최소화한다.

기존 6d736aedafc9 Migration은 수정하지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "417184ea4527"
down_revision: Union[str, Sequence[str], None] = "6d736aedafc9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "backtest_run",
        sa.Column("strategy_definition_id", sa.BigInteger(), nullable=True),
        schema="backtest",
    )
    op.add_column(
        "backtest_run",
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        schema="backtest",
    )
    op.create_foreign_key(
        "fk_backtest_run_strategy_definition",
        "backtest_run",
        "strategy_definition",
        ["strategy_definition_id"],
        ["strategy_id"],
        source_schema="backtest",
        referent_schema="trading",
        ondelete="RESTRICT",
    )
    op.create_index(
        "ux_backtest_run_idempotency_key",
        "backtest_run",
        ["idempotency_key"],
        unique=True,
        schema="backtest",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_backtest_run_strategy_definition",
        "backtest_run",
        ["strategy_definition_id"],
        unique=False,
        schema="backtest",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_backtest_run_strategy_definition",
        table_name="backtest_run",
        schema="backtest",
    )
    op.drop_index(
        "ux_backtest_run_idempotency_key",
        table_name="backtest_run",
        schema="backtest",
    )
    op.drop_constraint(
        "fk_backtest_run_strategy_definition",
        "backtest_run",
        schema="backtest",
        type_="foreignkey",
    )
    op.drop_column("backtest_run", "idempotency_key", schema="backtest")
    op.drop_column("backtest_run", "strategy_definition_id", schema="backtest")
