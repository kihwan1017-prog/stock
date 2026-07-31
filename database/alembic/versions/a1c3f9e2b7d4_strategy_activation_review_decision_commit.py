"""STEP 12-17 — Strategy Activation Review Package / Decision / Commit

Revision ID: a1c3f9e2b7d4
Revises: eba1e5446ab3
Create Date: 2026-07-30

PROMOTION_COMMITTED 상태인 Strategy Definition을 대상으로 Activation
Review Package(불변 Snapshot Report) → Human Activation Decision(불변
기록) → Activation Commit(불변 기록)까지 저장하는 3개 신규 테이블을
추가한다.

Strategy Promotion State/History(`trading.strategy_promotion_state`,
`trading.strategy_promotion_history`)는 STEP12-16R에서 이미 생성됐고
그대로 재사용한다 — 이 Migration은 그 두 테이블을 전혀 건드리지 않는다.
`PROMOTION_COMMITTED -> ACTIVATION_REVIEW -> ACTIVATED` 전이는 기존
History 테이블에 새 행으로만 추가된다(스키마 변경 없음).

개발 DB에는 기존 Activation 관련 행이 존재할 수 없으므로(신규 개념)
Backfill 정책은 필요하지 않다 — 빈 상태로 테이블만 생성한다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1c3f9e2b7d4"
down_revision: Union[str, Sequence[str], None] = "eba1e5446ab3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_activation_review_package",
        sa.Column("activation_review_package_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
                name="fk_activation_review_package_strategy_definition",
            ),
            nullable=False,
        ),
        sa.Column(
            "promotion_commit_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_promotion_commit.promotion_commit_id", ondelete="RESTRICT",
                name="fk_activation_review_package_promotion_commit",
            ),
            nullable=False,
        ),
        sa.Column("requested_market_type", sa.String(length=20), nullable=False),
        sa.Column("requested_broker_code", sa.String(length=20), nullable=False),
        sa.Column("requested_account_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "requested_user_broker_account_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.user_broker_account.user_broker_account_id", ondelete="RESTRICT",
                name="fk_activation_review_package_user_broker_account",
            ),
            nullable=True,
        ),
        sa.Column(
            "requested_paper_account_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.paper_account.account_id", ondelete="RESTRICT",
                name="fk_activation_review_package_paper_account",
            ),
            nullable=True,
        ),
        sa.Column("requested_execution_mode", sa.String(length=20), nullable=False),
        sa.Column("requested_runtime_scope_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_capital_limit", sa.Numeric(20, 4), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("effective_risk_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("account_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("broker_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("operational_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("readiness_status", sa.String(length=30), nullable=False),
        sa.Column("blocking_reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warning_reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("missing_requirement_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_input_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        schema="trading",
    )
    op.create_index(
        "ix_activation_review_package_strategy_definition", "strategy_activation_review_package",
        ["strategy_definition_id"], unique=False, schema="trading",
    )
    op.create_index(
        "ix_activation_review_package_promotion_commit", "strategy_activation_review_package",
        ["promotion_commit_id"], unique=False, schema="trading",
    )
    op.create_index(
        "ux_activation_review_package_idempotency_key", "strategy_activation_review_package",
        ["idempotency_key"], unique=True, schema="trading",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_activation_decision",
        sa.Column("activation_decision_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "activation_review_package_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_activation_review_package.activation_review_package_id", ondelete="RESTRICT",
                name="fk_activation_decision_package",
            ),
            nullable=False,
        ),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
                name="fk_activation_decision_strategy_definition",
            ),
            nullable=False,
        ),
        sa.Column("decision_type", sa.String(length=40), nullable=False),
        sa.Column("reason_code", sa.String(length=60), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("checklist_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("acknowledged_warnings_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("same_actor_warning", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("decided_by", sa.String(length=100), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_input_hash", sa.String(length=64), nullable=False),
        sa.Column("activation_ready", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("activation_review_package_id", name="uq_activation_decision_package"),
        schema="trading",
    )
    op.create_index(
        "ux_activation_decision_idempotency_key", "strategy_activation_decision",
        ["idempotency_key"], unique=True, schema="trading",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_activation_commit",
        sa.Column("activation_commit_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
                name="fk_activation_commit_strategy_definition",
            ),
            nullable=False,
        ),
        sa.Column(
            "promotion_commit_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_promotion_commit.promotion_commit_id", ondelete="RESTRICT",
                name="fk_activation_commit_promotion_commit",
            ),
            nullable=False,
        ),
        sa.Column(
            "activation_review_package_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_activation_review_package.activation_review_package_id", ondelete="RESTRICT",
                name="fk_activation_commit_package",
            ),
            nullable=False,
        ),
        sa.Column(
            "activation_decision_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_activation_decision.activation_decision_id", ondelete="RESTRICT",
                name="fk_activation_commit_decision",
            ),
            nullable=False,
        ),
        sa.Column("target_market_type", sa.String(length=20), nullable=False),
        sa.Column("target_broker_code", sa.String(length=20), nullable=False),
        sa.Column("target_account_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "target_user_broker_account_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.user_broker_account.user_broker_account_id", ondelete="RESTRICT",
                name="fk_activation_commit_user_broker_account",
            ),
            nullable=True,
        ),
        sa.Column(
            "target_paper_account_id", sa.BigInteger(),
            sa.ForeignKey(
                "trading.paper_account.account_id", ondelete="RESTRICT",
                name="fk_activation_commit_paper_account",
            ),
            nullable=True,
        ),
        sa.Column("execution_mode", sa.String(length=20), nullable=False),
        sa.Column("runtime_scope_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("account_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("credential_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("previous_promotion_status", sa.String(length=30), nullable=False),
        sa.Column("committed_promotion_status", sa.String(length=30), nullable=False),
        sa.Column("review_input_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_input_hash", sa.String(length=64), nullable=False),
        sa.Column("commit_reason", sa.Text(), nullable=False),
        sa.Column("confirmation_hash", sa.String(length=64), nullable=False),
        sa.Column("activation_commit_hash", sa.String(length=64), nullable=False),
        sa.Column("committed_by", sa.String(length=100), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("strategy_definition_id", name="uq_activation_commit_strategy_definition"),
        sa.UniqueConstraint("activation_review_package_id", name="uq_activation_commit_package"),
        sa.UniqueConstraint("activation_decision_id", name="uq_activation_commit_decision"),
        schema="trading",
    )
    op.create_index(
        "ix_activation_commit_strategy_definition", "strategy_activation_commit",
        ["strategy_definition_id"], unique=False, schema="trading",
    )
    op.create_index(
        "ux_activation_commit_idempotency_key", "strategy_activation_commit",
        ["idempotency_key"], unique=True, schema="trading",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_activation_commit_idempotency_key", table_name="strategy_activation_commit", schema="trading")
    op.drop_index("ix_activation_commit_strategy_definition", table_name="strategy_activation_commit", schema="trading")
    op.drop_table("strategy_activation_commit", schema="trading")

    op.drop_index("ux_activation_decision_idempotency_key", table_name="strategy_activation_decision", schema="trading")
    op.drop_table("strategy_activation_decision", schema="trading")

    op.drop_index("ux_activation_review_package_idempotency_key", table_name="strategy_activation_review_package", schema="trading")
    op.drop_index("ix_activation_review_package_promotion_commit", table_name="strategy_activation_review_package", schema="trading")
    op.drop_index("ix_activation_review_package_strategy_definition", table_name="strategy_activation_review_package", schema="trading")
    op.drop_table("strategy_activation_review_package", schema="trading")
