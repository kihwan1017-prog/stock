"""STEP 12-18R — Runtime Registration Rework: Scope Uniqueness / History

Revision ID: e2b6d1a9f374
Revises: c7e4a2f8d915
Create Date: 2026-08-01

STEP12-18 FAIL 사유(재작업 핵심): `strategy_runtime_registration_commit`/
`strategy_runtime_registry`에 `strategy_definition_id` 단독 UNIQUE가
있어, 동일 Strategy가 서로 다른 정상 Runtime Scope(다른 Account/User/
Execution Mode/Version)에 각각 등록되는 것을 막고 있었다. 이 Migration은
그 잘못된 제약을 제거하고, 유일성 기준을 `runtime_scope_hash` 단독으로
제한한다(이미 두 테이블 모두 `runtime_scope_hash` UNIQUE는 갖고 있었으므로
잘못된 제약만 DROP한다).

또한 동적 합성이 아닌 영속 불변 `strategy_runtime_registration_history`
테이블을 신설한다(INSERT ONLY, UPDATE/DELETE API 없음).

개발 DB에는 기존 Runtime Registration 관련 행이 없음을 재확인했으므로
(§ 완료보고 확인) Backfill 정책은 필요하지 않다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2b6d1a9f374"
down_revision: Union[str, Sequence[str], None] = "c7e4a2f8d915"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_runtime_reg_commit_strategy_definition", "strategy_runtime_registration_commit",
        schema="trading", type_="unique",
    )
    op.drop_constraint(
        "uq_runtime_registry_strategy_definition", "strategy_runtime_registry",
        schema="trading", type_="unique",
    )

    op.create_table(
        "strategy_runtime_registration_history",
        sa.Column("history_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_runtime_reg_history_strategy_definition"),
            nullable=False,
        ),
        sa.Column("runtime_scope_hash", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("previous_status", sa.String(length=40), nullable=True),
        sa.Column("current_status", sa.String(length=40), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("metadata_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_hash", name="uq_runtime_reg_history_event_hash"),
        schema="trading",
    )
    op.create_index(
        "ix_runtime_reg_history_strategy_definition", "strategy_runtime_registration_history",
        ["strategy_definition_id"], unique=False, schema="trading",
    )
    op.create_index(
        "ix_runtime_reg_history_occurred_at", "strategy_runtime_registration_history",
        ["occurred_at"], unique=False, schema="trading",
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_reg_history_occurred_at", table_name="strategy_runtime_registration_history", schema="trading")
    op.drop_index("ix_runtime_reg_history_strategy_definition", table_name="strategy_runtime_registration_history", schema="trading")
    op.drop_table("strategy_runtime_registration_history", schema="trading")

    op.create_unique_constraint(
        "uq_runtime_registry_strategy_definition", "strategy_runtime_registry",
        ["strategy_definition_id"], schema="trading",
    )
    op.create_unique_constraint(
        "uq_runtime_reg_commit_strategy_definition", "strategy_runtime_registration_commit",
        ["strategy_definition_id"], schema="trading",
    )
