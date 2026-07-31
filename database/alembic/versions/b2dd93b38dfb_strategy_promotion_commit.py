"""STEP 12-16 — Strategy Promotion Commit 저장

Revision ID: b2dd93b38dfb
Revises: d73cd201441a
Create Date: 2026-07-29

STEP12-15 Decision Package/Human Decision(APPROVE_FOR_PROMOTION)이 이미
검증된 이후, 관리자의 명시적 Promotion Commit 요청을 불변으로 기록한다.
Activation/Deployment/Runtime 등록은 전혀 포함하지 않는다.

Lifecycle 설계 결정: 기존 `ai.candidate_lifecycle.lifecycle_status`의
`PROMOTED`는 STEP11 "AI Candidate Promotion Gateway"(Candidate가
Strategy Request 생성 자격을 얻는 훨씬 이른 단계)를 의미하고, 이
STEP12-16의 "Strategy Definition Promotion"은 그보다 훨씬 뒤(Backtest/
Quality Gate/Explainability/Decision Package 검토 완료) 단계의 별개
개념이라 같은 필드를 재전이시키지 않는다(두 Lifecycle 개념 충돌 방지 —
기존 Enum에 새 값을 추가하지도, 기존 값을 다른 의미로 전용하지도
않음). `previous_lifecycle_status`/`committed_lifecycle_status`는 이
테이블 자신에만 기록되는 정보용 스냅샷/라벨이다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2dd93b38dfb"
down_revision: Union[str, Sequence[str], None] = "d73cd201441a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_promotion_commit",
        sa.Column("promotion_commit_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_definition.strategy_id",
                ondelete="RESTRICT",
                name="fk_promotion_commit_strategy_definition",
            ),
            nullable=False,
        ),
        sa.Column("candidate_id", sa.BigInteger(), nullable=True),
        sa.Column("strategy_request_id", sa.BigInteger(), nullable=True),
        sa.Column("approval_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "decision_package_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_decision_package.package_id",
                ondelete="RESTRICT",
                name="fk_promotion_commit_decision_package",
            ),
            nullable=False,
        ),
        sa.Column(
            "human_decision_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_human_decision.decision_id",
                ondelete="RESTRICT",
                name="fk_promotion_commit_human_decision",
            ),
            nullable=False,
        ),
        sa.Column("previous_lifecycle_status", sa.String(length=40), nullable=True),
        sa.Column("committed_lifecycle_status", sa.String(length=40), nullable=False),
        sa.Column("strategy_definition_version", sa.Integer(), nullable=True),
        sa.Column("definition_hash", sa.String(length=64), nullable=True),
        sa.Column("executable_hash", sa.String(length=64), nullable=True),
        sa.Column("approval_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("package_input_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_input_hash", sa.String(length=64), nullable=False),
        sa.Column("promotion_readiness_hash", sa.String(length=64), nullable=False),
        sa.Column("source_report_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("commit_reason", sa.Text(), nullable=False),
        sa.Column("confirmation_hash", sa.String(length=64), nullable=False),
        sa.Column("committed_by", sa.String(length=100), nullable=False),
        sa.Column(
            "committed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("promotion_commit_hash", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        schema="trading",
    )
    op.create_index(
        "ux_promotion_commit_strategy_id", "strategy_promotion_commit", ["strategy_definition_id"],
        unique=True, schema="trading",
    )
    op.create_index(
        "ux_promotion_commit_human_decision_id", "strategy_promotion_commit", ["human_decision_id"],
        unique=True, schema="trading",
    )
    op.create_index(
        "ux_promotion_commit_idempotency_key", "strategy_promotion_commit", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_promotion_commit_hash", "strategy_promotion_commit", ["promotion_commit_hash"],
        unique=False, schema="trading",
    )
    op.create_index(
        "ix_promotion_commit_decision_package_id", "strategy_promotion_commit", ["decision_package_id"],
        unique=False, schema="trading",
    )


def downgrade() -> None:
    op.drop_index("ix_promotion_commit_decision_package_id", table_name="strategy_promotion_commit", schema="trading")
    op.drop_index("ix_promotion_commit_hash", table_name="strategy_promotion_commit", schema="trading")
    op.drop_index("ux_promotion_commit_idempotency_key", table_name="strategy_promotion_commit", schema="trading")
    op.drop_index("ux_promotion_commit_human_decision_id", table_name="strategy_promotion_commit", schema="trading")
    op.drop_index("ux_promotion_commit_strategy_id", table_name="strategy_promotion_commit", schema="trading")
    op.drop_table("strategy_promotion_commit", schema="trading")
