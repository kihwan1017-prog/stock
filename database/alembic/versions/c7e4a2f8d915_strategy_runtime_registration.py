"""STEP 12-18 — Strategy Runtime Registration Package / Decision / Commit / Registry

Revision ID: c7e4a2f8d915
Revises: a1c3f9e2b7d4
Create Date: 2026-07-31

ACTIVATED 상태의 Strategy Definition을 대상으로 Runtime Registration
Review Package(불변 Snapshot) → Human Runtime Registration Decision(불변
기록) → Runtime Registration Commit(불변 기록) → Runtime Registry(비실행
등록, `enabled=false`/`running=false`)까지 저장하는 4개 신규 테이블을
추가한다.

Strategy Promotion State/History(`trading.strategy_promotion_state`,
`trading.strategy_promotion_history`)는 전혀 건드리지 않는다 — Runtime
Registration은 Promotion State 축(ACTIVATED)과는 별개의 새로운 "등록
여부" 개념이다. 기존 `trading.account_strategy_link`/
`trading.strategy_deployment`도 이 Migration에서 스키마 변경하지 않는다
(읽기 전용 충돌 조회 + 필요 시 비활성 Link 신규 INSERT만 수행).

개발 DB에는 기존 Runtime Registration 관련 행이 존재할 수 없으므로(신규
개념) Backfill 정책은 필요하지 않다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7e4a2f8d915"
down_revision: Union[str, Sequence[str], None] = "a1c3f9e2b7d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_runtime_registration_package",
        sa.Column("runtime_registration_package_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_runtime_reg_package_strategy_definition"),
            nullable=False,
        ),
        sa.Column(
            "activation_commit_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_activation_commit.activation_commit_id", ondelete="RESTRICT", name="fk_runtime_reg_package_activation_commit"),
            nullable=False,
        ),
        sa.Column(
            "activation_decision_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_activation_decision.activation_decision_id", ondelete="RESTRICT", name="fk_runtime_reg_package_activation_decision"),
            nullable=False,
        ),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("target_account_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "target_user_broker_account_id", sa.BigInteger(),
            sa.ForeignKey("trading.user_broker_account.user_broker_account_id", ondelete="RESTRICT", name="fk_runtime_reg_package_user_broker_account"),
            nullable=True,
        ),
        sa.Column(
            "target_paper_account_id", sa.BigInteger(),
            sa.ForeignKey("trading.paper_account.account_id", ondelete="RESTRICT", name="fk_runtime_reg_package_paper_account"),
            nullable=True,
        ),
        sa.Column("target_market_type", sa.String(length=20), nullable=False),
        sa.Column("target_broker_code", sa.String(length=20), nullable=False),
        sa.Column("execution_mode", sa.String(length=20), nullable=False),
        sa.Column("strategy_version", sa.Integer(), nullable=True),
        sa.Column("runtime_scope_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("account_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("credential_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("operational_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("activation_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("registration_readiness_status", sa.String(length=30), nullable=False),
        sa.Column("blocking_reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warning_reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("missing_requirement_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("registration_input_hash", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        schema="trading",
    )
    op.create_index("ix_runtime_reg_package_strategy_definition", "strategy_runtime_registration_package", ["strategy_definition_id"], unique=False, schema="trading")
    op.create_index("ix_runtime_reg_package_activation_commit", "strategy_runtime_registration_package", ["activation_commit_id"], unique=False, schema="trading")
    op.create_index(
        "ux_runtime_reg_package_idempotency_key", "strategy_runtime_registration_package", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_runtime_registration_decision",
        sa.Column("runtime_registration_decision_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "runtime_registration_package_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registration_package.runtime_registration_package_id", ondelete="RESTRICT", name="fk_runtime_reg_decision_package"),
            nullable=False,
        ),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_runtime_reg_decision_strategy_definition"),
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
        sa.Column("registration_ready", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("runtime_registration_package_id", name="uq_runtime_reg_decision_package"),
        schema="trading",
    )
    op.create_index(
        "ux_runtime_reg_decision_idempotency_key", "strategy_runtime_registration_decision", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_runtime_registration_commit",
        sa.Column("runtime_registration_commit_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_runtime_reg_commit_strategy_definition"),
            nullable=False,
        ),
        sa.Column(
            "activation_commit_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_activation_commit.activation_commit_id", ondelete="RESTRICT", name="fk_runtime_reg_commit_activation_commit"),
            nullable=False,
        ),
        sa.Column(
            "runtime_registration_package_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registration_package.runtime_registration_package_id", ondelete="RESTRICT", name="fk_runtime_reg_commit_package"),
            nullable=False,
        ),
        sa.Column(
            "runtime_registration_decision_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registration_decision.runtime_registration_decision_id", ondelete="RESTRICT", name="fk_runtime_reg_commit_decision"),
            nullable=False,
        ),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("account_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "target_user_broker_account_id", sa.BigInteger(),
            sa.ForeignKey("trading.user_broker_account.user_broker_account_id", ondelete="RESTRICT", name="fk_runtime_reg_commit_user_broker_account"),
            nullable=True,
        ),
        sa.Column(
            "target_paper_account_id", sa.BigInteger(),
            sa.ForeignKey("trading.paper_account.account_id", ondelete="RESTRICT", name="fk_runtime_reg_commit_paper_account"),
            nullable=True,
        ),
        sa.Column("market_type", sa.String(length=20), nullable=False),
        sa.Column("broker_code", sa.String(length=20), nullable=False),
        sa.Column("execution_mode", sa.String(length=20), nullable=False),
        sa.Column("strategy_version", sa.Integer(), nullable=True),
        sa.Column("runtime_scope_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("account_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("credential_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("operational_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("registration_input_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_input_hash", sa.String(length=64), nullable=False),
        sa.Column("confirmation_hash", sa.String(length=64), nullable=False),
        sa.Column("registration_commit_hash", sa.String(length=64), nullable=False),
        sa.Column("committed_by", sa.String(length=100), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("strategy_definition_id", name="uq_runtime_reg_commit_strategy_definition"),
        sa.UniqueConstraint("runtime_registration_package_id", name="uq_runtime_reg_commit_package"),
        sa.UniqueConstraint("runtime_registration_decision_id", name="uq_runtime_reg_commit_decision"),
        sa.UniqueConstraint("runtime_scope_hash", name="uq_runtime_reg_commit_scope_hash"),
        schema="trading",
    )
    op.create_index("ix_runtime_reg_commit_strategy_definition", "strategy_runtime_registration_commit", ["strategy_definition_id"], unique=False, schema="trading")
    op.create_index(
        "ux_runtime_reg_commit_idempotency_key", "strategy_runtime_registration_commit", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_runtime_registry",
        sa.Column("runtime_registry_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_runtime_registry_strategy_definition"),
            nullable=False,
        ),
        sa.Column(
            "runtime_registration_commit_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registration_commit.runtime_registration_commit_id", ondelete="RESTRICT", name="fk_runtime_registry_commit"),
            nullable=False,
        ),
        sa.Column("runtime_scope_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.Integer(), nullable=True),
        sa.Column("account_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "target_user_broker_account_id", sa.BigInteger(),
            sa.ForeignKey("trading.user_broker_account.user_broker_account_id", ondelete="RESTRICT", name="fk_runtime_registry_user_broker_account"),
            nullable=True,
        ),
        sa.Column(
            "target_paper_account_id", sa.BigInteger(),
            sa.ForeignKey("trading.paper_account.account_id", ondelete="RESTRICT", name="fk_runtime_registry_paper_account"),
            nullable=True,
        ),
        sa.Column("market_type", sa.String(length=20), nullable=False),
        sa.Column("broker_code", sa.String(length=20), nullable=False),
        sa.Column("execution_mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'REGISTERED'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("running", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("registered_by", sa.String(length=100), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("strategy_definition_id", name="uq_runtime_registry_strategy_definition"),
        sa.UniqueConstraint("runtime_scope_hash", name="uq_runtime_registry_scope_hash"),
        sa.UniqueConstraint("runtime_registration_commit_id", name="uq_runtime_registry_commit"),
        schema="trading",
    )
    op.create_index("ix_runtime_registry_strategy_definition", "strategy_runtime_registry", ["strategy_definition_id"], unique=False, schema="trading")


def downgrade() -> None:
    op.drop_index("ix_runtime_registry_strategy_definition", table_name="strategy_runtime_registry", schema="trading")
    op.drop_table("strategy_runtime_registry", schema="trading")

    op.drop_index("ux_runtime_reg_commit_idempotency_key", table_name="strategy_runtime_registration_commit", schema="trading")
    op.drop_index("ix_runtime_reg_commit_strategy_definition", table_name="strategy_runtime_registration_commit", schema="trading")
    op.drop_table("strategy_runtime_registration_commit", schema="trading")

    op.drop_index("ux_runtime_reg_decision_idempotency_key", table_name="strategy_runtime_registration_decision", schema="trading")
    op.drop_table("strategy_runtime_registration_decision", schema="trading")

    op.drop_index("ux_runtime_reg_package_idempotency_key", table_name="strategy_runtime_registration_package", schema="trading")
    op.drop_index("ix_runtime_reg_package_activation_commit", table_name="strategy_runtime_registration_package", schema="trading")
    op.drop_index("ix_runtime_reg_package_strategy_definition", table_name="strategy_runtime_registration_package", schema="trading")
    op.drop_table("strategy_runtime_registration_package", schema="trading")
