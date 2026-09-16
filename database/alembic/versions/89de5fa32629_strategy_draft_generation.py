"""STEP 12-2-2 — AI Strategy Draft Generator (Generation Run / Attempt)

Revision ID: 89de5fa32629
Revises: 5b999d920792
Create Date: 2026-07-28

승인(APPROVED)된 Strategy Request와 유효한 Candidate를 근거로 AI가
구조화된 Strategy Draft 초안을 생성하는 기반 구조를 위한 테이블 2개를
신설한다. Prompt Template/Output Schema는 신규 테이블을 만들지 않고
기존 ai.prompt_template/ai.prompt_template_version/ai.output_schema
(STEP 11-4)를 애플리케이션 레벨에서 get-or-create로 재사용한다(seed.py).

- ai.strategy_draft_generation_run: 생성 요청 1건(Request 단위).
  strategy_request_id/candidate_id(RESTRICT) FK. 동일 strategy_request에
  대해 PENDING/RUNNING(활성) 상태 Run은 부분 유니크 인덱스로 1개만
  허용한다. (strategy_request_id, idempotency_key) 조합은 UniqueConstraint로
  유일성을 강제한다(멱등성). draft_id는 성공 시에만 채워지는 nullable FK.
- ai.strategy_draft_generation_attempt: 그 Run 안에서 실제로 이뤄진
  Provider 호출 1회(재시도 시 새 Attempt). generation_run_id(RESTRICT) FK,
  (generation_run_id, attempt_no) UniqueConstraint. Hard Delete 금지 —
  FK는 History/Provenance 보존 원칙에 따라 RESTRICT.

기존 5b999d920792 Migration은 수정하지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "89de5fa32629"
down_revision: Union[str, Sequence[str], None] = "5b999d920792"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_draft_generation_run",
        sa.Column(
            "generation_run_id", sa.BigInteger(), sa.Identity(), nullable=False
        ),
        sa.Column("strategy_request_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("draft_id", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "candidate_lifecycle_status_at_request",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "candidate_fingerprint_at_request", sa.String(length=64), nullable=True
        ),
        sa.Column(
            "strategy_request_fingerprint_at_review",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "candidate_provenance_fingerprint", sa.String(length=64), nullable=True
        ),
        sa.Column(
            "candidate_provenance_schema_version",
            sa.String(length=20),
            nullable=True,
        ),
        sa.Column("prompt_template_id", sa.BigInteger(), nullable=True),
        sa.Column("prompt_version_id", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("model_parameters", postgresql.JSONB(), nullable=True),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("retry_of_run_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "retry_number", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("requested_by", sa.String(length=100), nullable=False),
        sa.Column("executed_by", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "generation_run_id", name=op.f("pk_strategy_draft_generation_run")
        ),
        sa.ForeignKeyConstraint(
            ["strategy_request_id"],
            ["ai.strategy_request.strategy_request_id"],
            name="fk_ai_sdg_run_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["ai.candidate_lifecycle.candidate_id"],
            name="fk_ai_sdg_run_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["ai.strategy_draft.draft_id"],
            name="fk_ai_sdg_run_draft",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_run_id"],
            ["ai.strategy_draft_generation_run.generation_run_id"],
            name="fk_ai_sdg_run_retry_of",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "strategy_request_id",
            "idempotency_key",
            name="uq_ai_sdg_run_idempotency",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLED','TIMED_OUT')",
            name="ck_ai_sdg_run_status",
        ),
        sa.CheckConstraint("retry_number >= 0", name="ck_ai_sdg_run_retry_nonneg"),
        schema="ai",
    )
    op.create_index(
        "ux_ai_sdg_run_active",
        "strategy_draft_generation_run",
        ["strategy_request_id"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING')"),
    )
    op.create_index(
        "ix_ai_sdg_run_request",
        "strategy_draft_generation_run",
        ["strategy_request_id"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "ix_ai_sdg_run_status",
        "strategy_draft_generation_run",
        ["status"],
        unique=False,
        schema="ai",
    )

    op.create_table(
        "strategy_draft_generation_attempt",
        sa.Column(
            "generation_attempt_id", sa.BigInteger(), sa.Identity(), nullable=False
        ),
        sa.Column("generation_run_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("system_prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("user_prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("request_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("response_hash", sa.String(length=64), nullable=True),
        sa.Column("structured_response", postgresql.JSONB(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "generation_attempt_id",
            name=op.f("pk_strategy_draft_generation_attempt"),
        ),
        sa.ForeignKeyConstraint(
            ["generation_run_id"],
            ["ai.strategy_draft_generation_run.generation_run_id"],
            name="fk_ai_sdg_attempt_run",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "generation_run_id", "attempt_no", name="uq_ai_sdg_attempt_no"
        ),
        sa.CheckConstraint("attempt_no >= 1", name="ck_ai_sdg_attempt_no_positive"),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_sdg_attempt_input_tokens_nonneg",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_sdg_attempt_output_tokens_nonneg",
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_ai_sdg_attempt_total_tokens_nonneg",
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_ai_sdg_attempt_latency_nonneg",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_sdg_attempt_run",
        "strategy_draft_generation_attempt",
        ["generation_run_id"],
        unique=False,
        schema="ai",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_sdg_attempt_run",
        table_name="strategy_draft_generation_attempt",
        schema="ai",
    )
    op.drop_table("strategy_draft_generation_attempt", schema="ai")

    op.drop_index(
        "ix_ai_sdg_run_status",
        table_name="strategy_draft_generation_run",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_sdg_run_request",
        table_name="strategy_draft_generation_run",
        schema="ai",
    )
    op.drop_index(
        "ux_ai_sdg_run_active",
        table_name="strategy_draft_generation_run",
        schema="ai",
    )
    op.drop_table("strategy_draft_generation_run", schema="ai")
