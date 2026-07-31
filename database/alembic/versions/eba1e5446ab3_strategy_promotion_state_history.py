"""STEP 12-16R — Strategy Promotion State & History 저장

Revision ID: eba1e5446ab3
Revises: b2dd93b38dfb
Create Date: 2026-07-30

STEP12-16 재작업 핵심 사유: 기존 Promotion Commit 행은
`committed_lifecycle_status="PROMOTED"`를 기록만 했을 뿐, 실제로
전이시키는 별도 공식 상태 축이 없었다(Promotion Event Snapshot 저장
까지만 수행). 이 Migration이 그 공식 Source of Truth를 추가한다.

- `trading.strategy_promotion_state`: Strategy Definition당 현재
  Promotion State 1개(UNIQUE). Promotion Commit과 동일 Transaction
  에서만 전이한다(전용 Domain Service 경유, 일반 CRUD로 직접
  UPDATE하지 않음).
- `trading.strategy_promotion_history`: 상태 전이의 불변 History
  (INSERT ONLY). 동일 Promotion Commit + 동일 new_status 조합은 1개만
  허용(중복 전이 방지).

개발 DB에는 기존 `strategy_promotion_commit` 행이 없음을 확인했으므로
(§ 완료보고 Migration 항목) Backfill 정책은 필요하지 않다 — 빈 상태로
테이블만 생성한다.

Candidate Lifecycle(`ai.candidate_lifecycle`)은 이 Migration에서 전혀
건드리지 않는다(의미 변경 없음).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "eba1e5446ab3"
down_revision: Union[str, Sequence[str], None] = "b2dd93b38dfb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_promotion_state",
        sa.Column("strategy_promotion_state_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_definition.strategy_id",
                ondelete="RESTRICT",
                name="fk_promotion_state_strategy_definition",
            ),
            nullable=False,
        ),
        sa.Column("current_status", sa.String(length=30), nullable=False),
        sa.Column("status_version", sa.Integer(), nullable=False),
        sa.Column(
            "current_promotion_commit_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_promotion_commit.promotion_commit_id",
                ondelete="RESTRICT",
                name="fk_promotion_state_current_commit",
            ),
            nullable=True,
        ),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", sa.String(length=100), nullable=False),
        sa.UniqueConstraint("strategy_definition_id", name="uq_promotion_state_strategy_definition"),
        schema="trading",
    )
    op.create_index(
        "ix_promotion_state_current_commit_id", "strategy_promotion_state", ["current_promotion_commit_id"],
        unique=False, schema="trading",
    )

    op.create_table(
        "strategy_promotion_history",
        sa.Column("promotion_history_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_definition.strategy_id",
                ondelete="RESTRICT",
                name="fk_promotion_history_strategy_definition",
            ),
            nullable=False,
        ),
        sa.Column(
            "promotion_commit_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_promotion_commit.promotion_commit_id",
                ondelete="RESTRICT",
                name="fk_promotion_history_commit",
            ),
            nullable=False,
        ),
        sa.Column("previous_status", sa.String(length=30), nullable=False),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("transition_reason", sa.Text(), nullable=False),
        sa.Column("human_decision_id", sa.BigInteger(), nullable=False),
        sa.Column("decision_package_id", sa.BigInteger(), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("metadata_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "promotion_commit_id", "new_status", name="uq_promotion_history_commit_status"
        ),
        schema="trading",
    )
    op.create_index(
        "ix_promotion_history_strategy_definition", "strategy_promotion_history", ["strategy_definition_id"],
        unique=False, schema="trading",
    )
    op.create_index(
        "ix_promotion_history_occurred_at", "strategy_promotion_history", ["occurred_at"],
        unique=False, schema="trading",
    )
    op.create_index(
        "ux_promotion_history_event_hash", "strategy_promotion_history", ["event_hash"],
        unique=True, schema="trading",
    )


def downgrade() -> None:
    op.drop_index("ux_promotion_history_event_hash", table_name="strategy_promotion_history", schema="trading")
    op.drop_index("ix_promotion_history_occurred_at", table_name="strategy_promotion_history", schema="trading")
    op.drop_index("ix_promotion_history_strategy_definition", table_name="strategy_promotion_history", schema="trading")
    op.drop_table("strategy_promotion_history", schema="trading")

    op.drop_index("ix_promotion_state_current_commit_id", table_name="strategy_promotion_state", schema="trading")
    op.drop_table("strategy_promotion_state", schema="trading")
