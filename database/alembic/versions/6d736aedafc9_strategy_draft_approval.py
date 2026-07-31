"""STEP 12-3 — Strategy Draft 관리자 최종 승인 (Approval / Definition Provenance)

Revision ID: 6d736aedafc9
Revises: 89de5fa32629
Create Date: 2026-07-28

관리자가 검토 완료한 Strategy Draft를 최종 승인/반려/취소하고, 승인된
Draft로부터 불변의 Strategy Definition을 생성하기 위한 스키마 변경.

기존 trading.strategy_definition(STEP8-3)을 재사용한다(신규 중복 Strategy
테이블 없음) — Provenance/불변성 컬럼만 추가한다. Approval 도메인은
ai.strategy_draft_approval / ai.strategy_draft_approval_history 2개
테이블을 신설한다(Hard Delete 금지, FK RESTRICT).

trading.strategy_definition.approval_id <-> ai.strategy_draft_approval의
상호 참조(순환) 문제는 다음 순서로 해결한다:
    1) trading.strategy_definition에 컬럼만 먼저 추가(approval_id는 FK
       제약 없이 컬럼만 추가).
    2) ai.strategy_draft_approval/_history 테이블 생성(이 시점에는
       trading.strategy_definition이 이미 존재하므로 FK 생성 가능).
    3) trading.strategy_definition.approval_id에 FK 제약을 추가.
downgrade()는 역순으로 되돌린다.

기존 89de5fa32629 Migration은 수정하지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "6d736aedafc9"
down_revision: Union[str, Sequence[str], None] = "89de5fa32629"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- 1) trading.strategy_definition: Provenance/불변성 컬럼 추가 ----
    op.add_column(
        "strategy_definition",
        sa.Column("source_draft_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_definition",
        sa.Column("source_draft_version", sa.Integer(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_definition",
        sa.Column("source_draft_revision", sa.Integer(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_definition",
        sa.Column("strategy_request_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_definition",
        sa.Column("candidate_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_definition",
        sa.Column("candidate_fingerprint", sa.String(length=64), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_definition",
        sa.Column("approval_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_definition",
        sa.Column("schema_version", sa.String(length=20), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_definition",
        sa.Column("definition_version", sa.Integer(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_definition",
        sa.Column("definition_hash", sa.String(length=64), nullable=True),
        schema="trading",
    )
    op.create_foreign_key(
        "fk_strategy_definition_source_draft",
        "strategy_definition",
        "strategy_draft",
        ["source_draft_id"],
        ["draft_id"],
        source_schema="trading",
        referent_schema="ai",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_strategy_definition_request",
        "strategy_definition",
        "strategy_request",
        ["strategy_request_id"],
        ["strategy_request_id"],
        source_schema="trading",
        referent_schema="ai",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_strategy_definition_candidate",
        "strategy_definition",
        "candidate_lifecycle",
        ["candidate_id"],
        ["candidate_id"],
        source_schema="trading",
        referent_schema="ai",
        ondelete="RESTRICT",
    )

    # ---- 2) ai.strategy_draft_approval / _history ----
    op.create_table(
        "strategy_draft_approval",
        sa.Column("approval_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("draft_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_request_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_definition_id", sa.BigInteger(), nullable=True),
        sa.Column("generation_run_id", sa.BigInteger(), nullable=True),
        sa.Column("generation_attempt_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column(
            "candidate_fingerprint_at_approval", sa.String(length=64), nullable=True
        ),
        sa.Column(
            "candidate_provenance_fingerprint", sa.String(length=64), nullable=True
        ),
        sa.Column("prompt_version_id", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("draft_content_hash", sa.String(length=64), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=True),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("decided_by", sa.String(length=100), nullable=False),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("revoked_reason", sa.String(length=1000), nullable=True),
        sa.Column("revoked_by", sa.String(length=100), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("approval_id", name=op.f("pk_strategy_draft_approval")),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["ai.strategy_draft.draft_id"],
            name="fk_ai_sda_approval_draft", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_request_id"], ["ai.strategy_request.strategy_request_id"],
            name="fk_ai_sda_approval_request", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["ai.candidate_lifecycle.candidate_id"],
            name="fk_ai_sda_approval_candidate", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_definition_id"], ["trading.strategy_definition.strategy_id"],
            name="fk_ai_sda_approval_definition", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["generation_run_id"],
            ["ai.strategy_draft_generation_run.generation_run_id"],
            name="fk_ai_sda_approval_run", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["generation_attempt_id"],
            ["ai.strategy_draft_generation_attempt.generation_attempt_id"],
            name="fk_ai_sda_approval_attempt", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "draft_id", "idempotency_key", name="uq_ai_sda_approval_idempotency"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','REVOKED','SUPERSEDED')",
            name="ck_ai_sda_approval_status",
        ),
        sa.CheckConstraint(
            "length(reason) >= 1", name="ck_ai_sda_approval_reason_len"
        ),
        schema="ai",
    )
    op.create_index(
        "ux_ai_sda_approval_active_draft",
        "strategy_draft_approval",
        ["draft_id"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("status = 'APPROVED'"),
    )
    op.create_index(
        "ux_ai_sda_approval_active_request",
        "strategy_draft_approval",
        ["strategy_request_id"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("status = 'APPROVED'"),
    )
    op.create_index(
        "ix_ai_sda_approval_draft", "strategy_draft_approval", ["draft_id"],
        unique=False, schema="ai",
    )
    op.create_index(
        "ix_ai_sda_approval_request", "strategy_draft_approval",
        ["strategy_request_id"], unique=False, schema="ai",
    )
    op.create_index(
        "ix_ai_sda_approval_status", "strategy_draft_approval", ["status"],
        unique=False, schema="ai",
    )

    op.create_table(
        "strategy_draft_approval_history",
        sa.Column("history_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("approval_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=True),
        sa.Column("new_status", sa.String(length=20), nullable=True),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=True),
        sa.Column("draft_revision", sa.Integer(), nullable=True),
        sa.Column("strategy_definition_id", sa.BigInteger(), nullable=True),
        sa.Column("metadata_hash", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "history_id", name=op.f("pk_strategy_draft_approval_history")
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"], ["ai.strategy_draft_approval.approval_id"],
            name="fk_ai_sda_approval_hist_approval", ondelete="RESTRICT",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_sda_approval_hist_approval",
        "strategy_draft_approval_history",
        ["approval_id"],
        unique=False,
        schema="ai",
    )

    # ---- 3) trading.strategy_definition.approval_id에 FK 추가 ----
    op.create_foreign_key(
        "fk_strategy_definition_approval",
        "strategy_definition",
        "strategy_draft_approval",
        ["approval_id"],
        ["approval_id"],
        source_schema="trading",
        referent_schema="ai",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_strategy_definition_approval", "strategy_definition",
        schema="trading", type_="foreignkey",
    )

    op.drop_index(
        "ix_ai_sda_approval_hist_approval",
        table_name="strategy_draft_approval_history",
        schema="ai",
    )
    op.drop_table("strategy_draft_approval_history", schema="ai")

    op.drop_index(
        "ix_ai_sda_approval_status", table_name="strategy_draft_approval", schema="ai"
    )
    op.drop_index(
        "ix_ai_sda_approval_request", table_name="strategy_draft_approval", schema="ai"
    )
    op.drop_index(
        "ix_ai_sda_approval_draft", table_name="strategy_draft_approval", schema="ai"
    )
    op.drop_index(
        "ux_ai_sda_approval_active_request",
        table_name="strategy_draft_approval",
        schema="ai",
    )
    op.drop_index(
        "ux_ai_sda_approval_active_draft",
        table_name="strategy_draft_approval",
        schema="ai",
    )
    op.drop_table("strategy_draft_approval", schema="ai")

    op.drop_constraint(
        "fk_strategy_definition_candidate", "strategy_definition",
        schema="trading", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_strategy_definition_request", "strategy_definition",
        schema="trading", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_strategy_definition_source_draft", "strategy_definition",
        schema="trading", type_="foreignkey",
    )

    op.drop_column("strategy_definition", "definition_hash", schema="trading")
    op.drop_column("strategy_definition", "definition_version", schema="trading")
    op.drop_column("strategy_definition", "schema_version", schema="trading")
    op.drop_column("strategy_definition", "approval_id", schema="trading")
    op.drop_column("strategy_definition", "candidate_fingerprint", schema="trading")
    op.drop_column("strategy_definition", "candidate_id", schema="trading")
    op.drop_column("strategy_definition", "strategy_request_id", schema="trading")
    op.drop_column("strategy_definition", "source_draft_revision", schema="trading")
    op.drop_column("strategy_definition", "source_draft_version", schema="trading")
    op.drop_column("strategy_definition", "source_draft_id", schema="trading")
