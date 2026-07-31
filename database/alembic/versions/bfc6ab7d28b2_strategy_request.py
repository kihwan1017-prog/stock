"""STEP 12-1 — Strategy Request 승인 게이트 (strategy_request / strategy_request_history)

Revision ID: bfc6ab7d28b2
Revises: 84b4b4a8c996
Create Date: 2026-07-28

AI Candidate(ai.candidate_lifecycle)를 즉시 Strategy로 승격하지 않고,
사람(관리자) 심사를 거치는 Strategy Request 게이트를 위한 테이블 2개를
신설한다.

- ai.strategy_request: candidate_id(RESTRICT) / user_id(RESTRICT) /
  reviewer_user_id(nullable, RESTRICT) FK. 동일 candidate_id에 대해
  status='PENDING_REVIEW'인 행은 부분 유니크 인덱스로 1개만 허용한다.
- ai.strategy_request_history: strategy_request_id(CASCADE) FK, 상태
  변경 이력을 append-only로 보존한다(Hard Delete 없음).

STEP 2-5-1/2/3에서 구축한 계좌 FK 체계와는 무관하며, 이 마이그레이션은
그 마이그레이션들을 수정하지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bfc6ab7d28b2"
down_revision: Union[str, Sequence[str], None] = "84b4b4a8c996"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_request",
        sa.Column("strategy_request_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("reviewer_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'PENDING_REVIEW'"),
        ),
        sa.Column(
            "candidate_lifecycle_status_snapshot",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column("request_note", sa.String(length=1000), nullable=True),
        sa.Column("review_note", sa.String(length=1000), nullable=True),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "strategy_request_id", name=op.f("pk_strategy_request")
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["ai.candidate_lifecycle.candidate_id"],
            name="fk_ai_strategy_request_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.user.user_id"],
            name="fk_ai_strategy_request_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["auth.user.user_id"],
            name="fk_ai_strategy_request_reviewer",
            ondelete="RESTRICT",
        ),
        schema="ai",
    )
    op.create_index(
        "ux_ai_strategy_request_candidate_active",
        "strategy_request",
        ["candidate_id"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("status = 'PENDING_REVIEW'"),
    )
    op.create_index(
        "ix_ai_strategy_request_user",
        "strategy_request",
        ["user_id"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "ix_ai_strategy_request_status",
        "strategy_request",
        ["status"],
        unique=False,
        schema="ai",
    )

    op.create_table(
        "strategy_request_history",
        sa.Column("history_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("strategy_request_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=True),
        sa.Column("new_status", sa.String(length=20), nullable=True),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "history_id", name=op.f("pk_strategy_request_history")
        ),
        sa.ForeignKeyConstraint(
            ["strategy_request_id"],
            ["ai.strategy_request.strategy_request_id"],
            name="fk_ai_strategy_request_hist_request",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_strategy_request_hist_request",
        "strategy_request_history",
        ["strategy_request_id"],
        unique=False,
        schema="ai",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_strategy_request_hist_request",
        table_name="strategy_request_history",
        schema="ai",
    )
    op.drop_table("strategy_request_history", schema="ai")

    op.drop_index(
        "ix_ai_strategy_request_status",
        table_name="strategy_request",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_strategy_request_user",
        table_name="strategy_request",
        schema="ai",
    )
    op.drop_index(
        "ux_ai_strategy_request_candidate_active",
        table_name="strategy_request",
        schema="ai",
    )
    op.drop_table("strategy_request", schema="ai")
