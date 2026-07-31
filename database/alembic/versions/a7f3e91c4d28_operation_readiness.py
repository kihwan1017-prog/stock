"""STEP 12-20 — Operation Readiness Certification Package / Decision / Commit / History

Revision ID: a7f3e91c4d28
Revises: f4a8c2d6e103
Create Date: 2026-08-05

READY_TO_START(§ STEP12-19) Deployment를 대상으로 Strategy/Promotion/
Activation/Runtime Registration/Deployment/Scheduler Plan/Credential/
Risk/Trading Flag/Kill Switch/Recovery/Account/Runtime Scope/Deployment
Scope/History/Audit 15개 영역을 하나의 Certification으로 묶는 Operation
Readiness Package(불변 Snapshot) → Human Operation Decision(불변 기록) →
Operation Commit(불변 기록)까지 저장하는 4개 신규 테이블을 추가한다.

기존 `trading.strategy_deployment`는 스키마 변경 없이 그대로 재사용한다
— `status_code` 컬럼은 이미 plain VARCHAR이므로 신규 값
"READY_TO_OPERATE"(`StrategyDeploymentStatus.READY_TO_OPERATE`, Python
Enum에만 추가)를 저장하는 데 Migration이 필요하지 않다. Runtime Scope
유일성은 신규 `strategy_operation_readiness_commit.runtime_scope_hash`
UNIQUE로 별도 보장한다(§ STEP12-19와 동일한 원칙).

개발 DB에는 기존 Operation Readiness 관련 행이 없음을 확인했으므로
Backfill 정책은 필요하지 않다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7f3e91c4d28"
down_revision: Union[str, Sequence[str], None] = "f4a8c2d6e103"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_operation_readiness_package",
        sa.Column("operation_readiness_package_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_op_readiness_package_strategy_definition"),
            nullable=False,
        ),
        sa.Column(
            "deployment_readiness_commit_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_deployment_readiness_commit.deployment_readiness_commit_id", ondelete="RESTRICT", name="fk_op_readiness_package_deployment_commit"),
            nullable=False,
        ),
        sa.Column(
            "runtime_registration_commit_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registration_commit.runtime_registration_commit_id", ondelete="RESTRICT", name="fk_op_readiness_package_registration_commit"),
            nullable=False,
        ),
        sa.Column(
            "runtime_registry_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registry.runtime_registry_id", ondelete="RESTRICT", name="fk_op_readiness_package_registry"),
            nullable=False,
        ),
        sa.Column(
            "strategy_deployment_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_deployment.strategy_deployment_id", ondelete="RESTRICT", name="fk_op_readiness_package_deployment"),
            nullable=False,
        ),
        sa.Column(
            "scheduler_plan_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_scheduler_plan.scheduler_plan_id", ondelete="RESTRICT", name="fk_op_readiness_package_scheduler_plan"),
            nullable=False,
        ),
        sa.Column("runtime_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("account_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "target_user_broker_account_id", sa.BigInteger(),
            sa.ForeignKey("trading.user_broker_account.user_broker_account_id", ondelete="RESTRICT", name="fk_op_readiness_package_user_broker_account"),
            nullable=True,
        ),
        sa.Column(
            "target_paper_account_id", sa.BigInteger(),
            sa.ForeignKey("trading.paper_account.account_id", ondelete="RESTRICT", name="fk_op_readiness_package_paper_account"),
            nullable=True,
        ),
        sa.Column("market_type", sa.String(length=20), nullable=False),
        sa.Column("broker_code", sa.String(length=20), nullable=False),
        sa.Column("execution_mode", sa.String(length=20), nullable=False),
        sa.Column("strategy_version", sa.BigInteger(), nullable=True),
        sa.Column("strategy_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("promotion_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("activation_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_registration_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deployment_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scheduler_plan_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("credential_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trading_flag_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("kill_switch_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recovery_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_scope_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deployment_scope_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("history_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("audit_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("readiness_status", sa.String(length=30), nullable=False),
        sa.Column("blocking_reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warning_reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("missing_requirement_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("certification_areas_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("operation_input_hash", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        schema="trading",
    )
    op.create_index("ix_op_readiness_package_strategy_definition", "strategy_operation_readiness_package", ["strategy_definition_id"], unique=False, schema="trading")
    op.create_index("ix_op_readiness_package_deployment_commit", "strategy_operation_readiness_package", ["deployment_readiness_commit_id"], unique=False, schema="trading")
    op.create_index(
        "ux_op_readiness_package_idempotency_key", "strategy_operation_readiness_package", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_operation_readiness_decision",
        sa.Column("operation_readiness_decision_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "operation_readiness_package_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_operation_readiness_package.operation_readiness_package_id", ondelete="RESTRICT", name="fk_op_readiness_decision_package"),
            nullable=False,
        ),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_op_readiness_decision_strategy_definition"),
            nullable=False,
        ),
        sa.Column("runtime_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_type", sa.String(length=40), nullable=False),
        sa.Column("reason_code", sa.String(length=60), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("checklist_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("acknowledged_warnings_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("same_actor_warning", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("decided_by", sa.String(length=100), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_input_hash", sa.String(length=64), nullable=False),
        sa.Column("operation_ready", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("operation_readiness_package_id", name="uq_op_readiness_decision_package"),
        schema="trading",
    )
    op.create_index(
        "ux_op_readiness_decision_idempotency_key", "strategy_operation_readiness_decision", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_operation_readiness_commit",
        sa.Column("operation_readiness_commit_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_op_readiness_commit_strategy_definition"),
            nullable=False,
        ),
        sa.Column(
            "deployment_readiness_commit_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_deployment_readiness_commit.deployment_readiness_commit_id", ondelete="RESTRICT", name="fk_op_readiness_commit_deployment_commit"),
            nullable=False,
        ),
        sa.Column(
            "runtime_registration_commit_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registration_commit.runtime_registration_commit_id", ondelete="RESTRICT", name="fk_op_readiness_commit_registration_commit"),
            nullable=False,
        ),
        sa.Column(
            "runtime_registry_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registry.runtime_registry_id", ondelete="RESTRICT", name="fk_op_readiness_commit_registry"),
            nullable=False,
        ),
        sa.Column(
            "strategy_deployment_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_deployment.strategy_deployment_id", ondelete="RESTRICT", name="fk_op_readiness_commit_deployment"),
            nullable=False,
        ),
        sa.Column(
            "scheduler_plan_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_scheduler_plan.scheduler_plan_id", ondelete="RESTRICT", name="fk_op_readiness_commit_scheduler_plan"),
            nullable=False,
        ),
        sa.Column(
            "operation_readiness_package_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_operation_readiness_package.operation_readiness_package_id", ondelete="RESTRICT", name="fk_op_readiness_commit_package"),
            nullable=False,
        ),
        sa.Column(
            "operation_readiness_decision_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_operation_readiness_decision.operation_readiness_decision_id", ondelete="RESTRICT", name="fk_op_readiness_commit_decision"),
            nullable=False,
        ),
        sa.Column("runtime_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("operation_input_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_input_hash", sa.String(length=64), nullable=False),
        sa.Column("confirmation_hash", sa.String(length=64), nullable=False),
        sa.Column("operation_commit_hash", sa.String(length=64), nullable=False),
        sa.Column("committed_by", sa.String(length=100), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("operation_readiness_package_id", name="uq_op_readiness_commit_package"),
        sa.UniqueConstraint("operation_readiness_decision_id", name="uq_op_readiness_commit_decision"),
        sa.UniqueConstraint("runtime_scope_hash", name="uq_op_readiness_commit_scope_hash"),
        schema="trading",
    )
    op.create_index("ix_op_readiness_commit_strategy_definition", "strategy_operation_readiness_commit", ["strategy_definition_id"], unique=False, schema="trading")
    op.create_index(
        "ux_op_readiness_commit_idempotency_key", "strategy_operation_readiness_commit", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_operation_readiness_history",
        sa.Column("history_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_op_readiness_history_strategy_definition"),
            nullable=False,
        ),
        sa.Column("runtime_scope_hash", sa.String(length=64), nullable=True),
        sa.Column("deployment_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("previous_status", sa.String(length=40), nullable=True),
        sa.Column("current_status", sa.String(length=40), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("metadata_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_hash", name="uq_op_readiness_history_event_hash"),
        schema="trading",
    )
    op.create_index("ix_op_readiness_history_strategy_definition", "strategy_operation_readiness_history", ["strategy_definition_id"], unique=False, schema="trading")
    op.create_index("ix_op_readiness_history_occurred_at", "strategy_operation_readiness_history", ["occurred_at"], unique=False, schema="trading")


def downgrade() -> None:
    op.drop_index("ix_op_readiness_history_occurred_at", table_name="strategy_operation_readiness_history", schema="trading")
    op.drop_index("ix_op_readiness_history_strategy_definition", table_name="strategy_operation_readiness_history", schema="trading")
    op.drop_table("strategy_operation_readiness_history", schema="trading")

    op.drop_index("ux_op_readiness_commit_idempotency_key", table_name="strategy_operation_readiness_commit", schema="trading")
    op.drop_index("ix_op_readiness_commit_strategy_definition", table_name="strategy_operation_readiness_commit", schema="trading")
    op.drop_table("strategy_operation_readiness_commit", schema="trading")

    op.drop_index("ux_op_readiness_decision_idempotency_key", table_name="strategy_operation_readiness_decision", schema="trading")
    op.drop_table("strategy_operation_readiness_decision", schema="trading")

    op.drop_index("ux_op_readiness_package_idempotency_key", table_name="strategy_operation_readiness_package", schema="trading")
    op.drop_index("ix_op_readiness_package_deployment_commit", table_name="strategy_operation_readiness_package", schema="trading")
    op.drop_index("ix_op_readiness_package_strategy_definition", table_name="strategy_operation_readiness_package", schema="trading")
    op.drop_table("strategy_operation_readiness_package", schema="trading")
