"""STEP 12-2-1 — Strategy Draft Domain (strategy_draft / strategy_draft_history)

Revision ID: 5b999d920792
Revises: 27d47b2bb048
Create Date: 2026-07-28

승인(APPROVED)된 Strategy Request 위에 Strategy Draft를 저장·버전관리하는
기반 구조를 위한 테이블 2개를 신설한다. AI 호출/Prompt 생성/LLM 실행은
이 마이그레이션/도메인의 범위가 아니다(STEP12-2-2 이후).

- ai.strategy_draft: strategy_request_id(RESTRICT) FK. 동일
  strategy_request_id에 대해 status='DRAFT'인 행은 부분 유니크 인덱스로
  1개만 허용한다. (strategy_request_id, version, revision) 조합은
  UniqueConstraint로 유일성을 강제한다.
- ai.strategy_draft_history: draft_id(RESTRICT — STEP12-1A에서 CASCADE가
  감사 이력 보존 원칙과 상충함을 확인해 처음부터 RESTRICT로 설계) FK,
  상태/버전/리비전 변경 이력을 append-only로 보존한다(Hard Delete 없음).

기존 27d47b2bb048 Migration은 수정하지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5b999d920792"
down_revision: Union[str, Sequence[str], None] = "27d47b2bb048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_draft",
        sa.Column("draft_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("strategy_request_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=2000), nullable=True),
        sa.Column("entry_rule", sa.Text(), nullable=True),
        sa.Column("exit_rule", sa.Text(), nullable=True),
        sa.Column("stop_loss_rule", sa.Text(), nullable=True),
        sa.Column("take_profit_rule", sa.Text(), nullable=True),
        sa.Column("position_sizing_rule", sa.Text(), nullable=True),
        sa.Column("timeframe", sa.String(length=20), nullable=False),
        sa.Column("market_type", sa.String(length=20), nullable=False),
        sa.Column("risk_parameters", postgresql.JSONB(), nullable=True),
        sa.Column("indicator_configuration", postgresql.JSONB(), nullable=True),
        sa.Column("llm_provider", sa.String(length=50), nullable=True),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=True),
        sa.Column("candidate_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
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
        sa.PrimaryKeyConstraint("draft_id", name=op.f("pk_strategy_draft")),
        sa.ForeignKeyConstraint(
            ["strategy_request_id"],
            ["ai.strategy_request.strategy_request_id"],
            name="fk_ai_strategy_draft_request",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "strategy_request_id",
            "version",
            "revision",
            name="uq_ai_strategy_draft_request_version_revision",
        ),
        schema="ai",
    )
    op.create_index(
        "ux_ai_strategy_draft_request_active",
        "strategy_draft",
        ["strategy_request_id"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("status = 'DRAFT'"),
    )
    op.create_index(
        "ix_ai_strategy_draft_request",
        "strategy_draft",
        ["strategy_request_id"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "ix_ai_strategy_draft_status",
        "strategy_draft",
        ["status"],
        unique=False,
        schema="ai",
    )

    op.create_table(
        "strategy_draft_history",
        sa.Column("history_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("draft_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=True),
        sa.Column("new_status", sa.String(length=20), nullable=True),
        sa.Column("previous_version", sa.Integer(), nullable=True),
        sa.Column("new_version", sa.Integer(), nullable=True),
        sa.Column("previous_revision", sa.Integer(), nullable=True),
        sa.Column("new_revision", sa.Integer(), nullable=True),
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
            "history_id", name=op.f("pk_strategy_draft_history")
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["ai.strategy_draft.draft_id"],
            name="fk_ai_strategy_draft_hist_draft",
            ondelete="RESTRICT",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_strategy_draft_hist_draft",
        "strategy_draft_history",
        ["draft_id"],
        unique=False,
        schema="ai",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_strategy_draft_hist_draft",
        table_name="strategy_draft_history",
        schema="ai",
    )
    op.drop_table("strategy_draft_history", schema="ai")

    op.drop_index(
        "ix_ai_strategy_draft_status",
        table_name="strategy_draft",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_strategy_draft_request",
        table_name="strategy_draft",
        schema="ai",
    )
    op.drop_index(
        "ux_ai_strategy_draft_request_active",
        table_name="strategy_draft",
        schema="ai",
    )
    op.drop_table("strategy_draft", schema="ai")
