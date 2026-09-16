"""STEP 12-19 — Deployment Readiness Package / Decision / Commit / Scheduler Plan / History

Revision ID: f4a8c2d6e103
Revises: e2b6d1a9f374
Create Date: 2026-08-01

REGISTERED(비실행) Runtime Registry를 대상으로 Deployment Readiness
Review Package(불변 Snapshot) → Human Deployment Decision(불변 기록) →
Deployment Commit(불변 기록)까지 저장하는 5개 신규 테이블을 추가한다.

기존 `trading.strategy_deployment`(STEP31-1)는 스키마 변경 없이 그대로
재사용한다 — `status_code` 컬럼은 이미 plain VARCHAR이므로 신규 값
"READY_TO_START"(`StrategyDeploymentStatus.READY_TO_START`, Python
Enum에만 추가)를 저장하는 데 Migration이 필요하지 않다. 기존
`uq_strategy_deployment_system_active`/`uq_strategy_deployment_user_active`
Partial Unique Index는 `status_code='ACTIVE'`에만 적용되므로 이 STEP과
무관하다 — Runtime Scope 유일성은 신규 `strategy_deployment_readiness_
commit.runtime_scope_hash` UNIQUE로 별도 보장한다.

개발 DB에는 기존 Deployment Readiness 관련 행이 없음을 확인했으므로
Backfill 정책은 필요하지 않다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4a8c2d6e103"
down_revision: Union[str, Sequence[str], None] = "e2b6d1a9f374"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # § STEP12-19 — 기존 `trading.strategy_deployment.strategy_performance
    # _run_id`는 STEP7-x류의 별개 "Performance Run" 개념을 가리키는 NOT
    # NULL FK였다. STEP12-x AI Strategy 파이프라인이 생성하는 Deployment는
    # 이 개념과 무관하므로(자체 Backtest/Quality Gate 근거 체계를 이미
    # 갖고 있음) NULL을 허용하도록 최소 변경한다 — 기존 값이 있는 행은
    # 전혀 건드리지 않고, 기존 호출부(PaperStrategyDeploymentService)도
    # 계속 값을 채워 넣으므로 하위 호환에 영향이 없다.
    op.alter_column(
        "strategy_deployment", "strategy_performance_run_id", nullable=True, schema="trading",
    )

    op.create_table(
        "strategy_deployment_readiness_package",
        sa.Column("deployment_readiness_package_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_deploy_readiness_package_strategy_definition"),
            nullable=False,
        ),
        sa.Column(
            "runtime_registration_commit_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registration_commit.runtime_registration_commit_id", ondelete="RESTRICT", name="fk_deploy_readiness_package_registration_commit"),
            nullable=False,
        ),
        sa.Column(
            "runtime_registry_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registry.runtime_registry_id", ondelete="RESTRICT", name="fk_deploy_readiness_package_registry"),
            nullable=False,
        ),
        sa.Column("runtime_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("account_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "target_user_broker_account_id", sa.BigInteger(),
            sa.ForeignKey("trading.user_broker_account.user_broker_account_id", ondelete="RESTRICT", name="fk_deploy_readiness_package_user_broker_account"),
            nullable=True,
        ),
        sa.Column(
            "target_paper_account_id", sa.BigInteger(),
            sa.ForeignKey("trading.paper_account.account_id", ondelete="RESTRICT", name="fk_deploy_readiness_package_paper_account"),
            nullable=True,
        ),
        sa.Column("market_type", sa.String(length=20), nullable=False),
        sa.Column("broker_code", sa.String(length=20), nullable=False),
        sa.Column("execution_mode", sa.String(length=20), nullable=False),
        sa.Column("strategy_version", sa.Integer(), nullable=True),
        sa.Column("deployment_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scheduler_plan_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("account_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("credential_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("operational_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recovery_snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("readiness_status", sa.String(length=30), nullable=False),
        sa.Column("blocking_reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warning_reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("missing_requirement_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deployment_input_hash", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        schema="trading",
    )
    op.create_index("ix_deploy_readiness_package_strategy_definition", "strategy_deployment_readiness_package", ["strategy_definition_id"], unique=False, schema="trading")
    op.create_index("ix_deploy_readiness_package_registration_commit", "strategy_deployment_readiness_package", ["runtime_registration_commit_id"], unique=False, schema="trading")
    op.create_index(
        "ux_deploy_readiness_package_idempotency_key", "strategy_deployment_readiness_package", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_deployment_readiness_decision",
        sa.Column("deployment_readiness_decision_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "deployment_readiness_package_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_deployment_readiness_package.deployment_readiness_package_id", ondelete="RESTRICT", name="fk_deploy_readiness_decision_package"),
            nullable=False,
        ),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_deploy_readiness_decision_strategy_definition"),
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
        sa.Column("deployment_ready", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("deployment_readiness_package_id", name="uq_deploy_readiness_decision_package"),
        schema="trading",
    )
    op.create_index(
        "ux_deploy_readiness_decision_idempotency_key", "strategy_deployment_readiness_decision", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_runtime_scheduler_plan",
        sa.Column("scheduler_plan_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "runtime_registry_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registry.runtime_registry_id", ondelete="RESTRICT", name="fk_scheduler_plan_registry"),
            nullable=False,
        ),
        sa.Column("runtime_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("scheduler_type", sa.String(length=30), nullable=False),
        sa.Column("timezone", sa.String(length=50), nullable=False),
        sa.Column("market_calendar", sa.String(length=50), nullable=False),
        sa.Column("cron_expression", sa.String(length=100), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("start_policy", sa.String(length=50), nullable=False),
        sa.Column("stop_policy", sa.String(length=50), nullable=False),
        sa.Column("market_open_offset", sa.Integer(), nullable=True),
        sa.Column("market_close_offset", sa.Integer(), nullable=True),
        sa.Column("holiday_policy", sa.String(length=50), nullable=False),
        sa.Column("retry_policy_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("misfire_policy_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("concurrency_policy_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("registered_to_scheduler", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("scheduler_job_id", sa.String(length=100), nullable=True),
        sa.Column("plan_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("runtime_scope_hash", "plan_version", name="uq_scheduler_plan_scope_version"),
        schema="trading",
    )
    op.create_index("ix_scheduler_plan_runtime_registry", "strategy_runtime_scheduler_plan", ["runtime_registry_id"], unique=False, schema="trading")

    op.create_table(
        "strategy_deployment_readiness_commit",
        sa.Column("deployment_readiness_commit_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_deploy_readiness_commit_strategy_definition"),
            nullable=False,
        ),
        sa.Column(
            "runtime_registration_commit_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registration_commit.runtime_registration_commit_id", ondelete="RESTRICT", name="fk_deploy_readiness_commit_registration_commit"),
            nullable=False,
        ),
        sa.Column(
            "runtime_registry_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_registry.runtime_registry_id", ondelete="RESTRICT", name="fk_deploy_readiness_commit_registry"),
            nullable=False,
        ),
        sa.Column(
            "deployment_readiness_package_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_deployment_readiness_package.deployment_readiness_package_id", ondelete="RESTRICT", name="fk_deploy_readiness_commit_package"),
            nullable=False,
        ),
        sa.Column(
            "deployment_readiness_decision_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_deployment_readiness_decision.deployment_readiness_decision_id", ondelete="RESTRICT", name="fk_deploy_readiness_commit_decision"),
            nullable=False,
        ),
        sa.Column("runtime_scope_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "strategy_deployment_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_deployment.strategy_deployment_id", ondelete="RESTRICT", name="fk_deploy_readiness_commit_deployment"),
            nullable=False,
        ),
        sa.Column(
            "scheduler_plan_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_runtime_scheduler_plan.scheduler_plan_id", ondelete="RESTRICT", name="fk_deploy_readiness_commit_scheduler_plan"),
            nullable=False,
        ),
        sa.Column("deployment_input_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_input_hash", sa.String(length=64), nullable=False),
        sa.Column("scheduler_plan_hash", sa.String(length=64), nullable=False),
        sa.Column("confirmation_hash", sa.String(length=64), nullable=False),
        sa.Column("deployment_commit_hash", sa.String(length=64), nullable=False),
        sa.Column("committed_by", sa.String(length=100), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("deployment_readiness_package_id", name="uq_deploy_readiness_commit_package"),
        sa.UniqueConstraint("deployment_readiness_decision_id", name="uq_deploy_readiness_commit_decision"),
        sa.UniqueConstraint("runtime_scope_hash", name="uq_deploy_readiness_commit_scope_hash"),
        schema="trading",
    )
    op.create_index("ix_deploy_readiness_commit_strategy_definition", "strategy_deployment_readiness_commit", ["strategy_definition_id"], unique=False, schema="trading")
    op.create_index(
        "ux_deploy_readiness_commit_idempotency_key", "strategy_deployment_readiness_commit", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_deployment_readiness_history",
        sa.Column("history_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_definition_id", sa.BigInteger(),
            sa.ForeignKey("trading.strategy_definition.strategy_id", ondelete="RESTRICT", name="fk_deploy_readiness_history_strategy_definition"),
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
        sa.UniqueConstraint("event_hash", name="uq_deploy_readiness_history_event_hash"),
        schema="trading",
    )
    op.create_index("ix_deploy_readiness_history_strategy_definition", "strategy_deployment_readiness_history", ["strategy_definition_id"], unique=False, schema="trading")
    op.create_index("ix_deploy_readiness_history_occurred_at", "strategy_deployment_readiness_history", ["occurred_at"], unique=False, schema="trading")


def downgrade() -> None:
    op.drop_index("ix_deploy_readiness_history_occurred_at", table_name="strategy_deployment_readiness_history", schema="trading")
    op.drop_index("ix_deploy_readiness_history_strategy_definition", table_name="strategy_deployment_readiness_history", schema="trading")
    op.drop_table("strategy_deployment_readiness_history", schema="trading")

    op.drop_index("ux_deploy_readiness_commit_idempotency_key", table_name="strategy_deployment_readiness_commit", schema="trading")
    op.drop_index("ix_deploy_readiness_commit_strategy_definition", table_name="strategy_deployment_readiness_commit", schema="trading")
    op.drop_table("strategy_deployment_readiness_commit", schema="trading")

    op.drop_index("ix_scheduler_plan_runtime_registry", table_name="strategy_runtime_scheduler_plan", schema="trading")
    op.drop_table("strategy_runtime_scheduler_plan", schema="trading")

    op.drop_index("ux_deploy_readiness_decision_idempotency_key", table_name="strategy_deployment_readiness_decision", schema="trading")
    op.drop_table("strategy_deployment_readiness_decision", schema="trading")

    op.drop_index("ux_deploy_readiness_package_idempotency_key", table_name="strategy_deployment_readiness_package", schema="trading")
    op.drop_index("ix_deploy_readiness_package_registration_commit", table_name="strategy_deployment_readiness_package", schema="trading")
    op.drop_index("ix_deploy_readiness_package_strategy_definition", table_name="strategy_deployment_readiness_package", schema="trading")
    op.drop_table("strategy_deployment_readiness_package", schema="trading")

    op.alter_column(
        "strategy_deployment", "strategy_performance_run_id", nullable=False, schema="trading",
    )
