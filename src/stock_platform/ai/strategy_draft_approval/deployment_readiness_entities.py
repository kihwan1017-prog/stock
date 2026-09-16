"""STEP 12-19 — Deployment Readiness Package / Decision / Commit / Scheduler
Plan / History.

STEP12-18(R)에서 비실행(enabled=false, running=false) 등록된 Runtime
Registry를 대상으로 실행 직전의 Deployment 구성과 Scheduler Plan을
확정한다. 이 STEP 어디에서도 Runtime을 시작하거나 Scheduler에 Job을
실제로 등록하거나 Broker에 연결하지 않는다 — `strategy_runtime_scheduler
_plan`은 `enabled=false`, `registered_to_scheduler=false`,
`scheduler_job_id=NULL`로만 저장되는 "미래 실행을 위한 계획"이며 실제
APScheduler Job Store와 무관하다.

핵심 도메인 결정 — 기존 `trading.strategy_deployment`(STEP31-1
PaperStrategyDeploymentService가 사용하는 진짜 실행 테이블)를 그대로
재사용하되, 그 테이블의 `status_code="ACTIVE"`는 이미 "실제 활성/실행
중"이라는 확립된 의미로 쓰이고 있으므로 절대 재사용하지 않는다.
`StrategyDeploymentStatus.READY_TO_START`(신규 추가값, `models.py`)를
전용으로 사용해 "START 직전까지 구성 확정" 의미를 명확히 분리한다(§
STEP12-16R/17/18에서 Candidate Lifecycle과 새 상태 축을 분리했던 것과
동일한 원칙).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base

READINESS_STATUS_READY = "READY_FOR_DEPLOYMENT"
READINESS_STATUS_BLOCKED = "BLOCKED"

DEPLOYMENT_DECISION_APPROVE = "APPROVE_DEPLOYMENT"
DEPLOYMENT_DECISION_REQUEST_CHANGES = "REQUEST_DEPLOYMENT_CHANGES"
DEPLOYMENT_DECISION_REJECT = "REJECT_DEPLOYMENT"
DEPLOYMENT_DECISION_TYPES = frozenset(
    {DEPLOYMENT_DECISION_APPROVE, DEPLOYMENT_DECISION_REQUEST_CHANGES, DEPLOYMENT_DECISION_REJECT}
)

SCHEDULER_TYPE_MARKET_SESSION = "MARKET_SESSION"
SCHEDULER_TYPE_CRON = "CRON"
SCHEDULER_TYPE_INTERVAL = "INTERVAL"
SCHEDULER_TYPE_MANUAL_START_ONLY = "MANUAL_START_ONLY"


class StrategyDeploymentReadinessPackageEntity(Base):
    __tablename__ = "strategy_deployment_readiness_package"
    __table_args__ = ({"schema": "trading"},)

    deployment_readiness_package_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_package_strategy_definition",
        ),
        nullable=False,
    )
    runtime_registration_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registration_commit.runtime_registration_commit_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_package_registration_commit",
        ),
        nullable=False,
    )
    runtime_registry_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registry.runtime_registry_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_package_registry",
        ),
        nullable=False,
    )
    runtime_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_user_id: Mapped[int | None] = mapped_column(BigInteger)
    account_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_package_user_broker_account",
        ),
    )
    target_paper_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_package_paper_account",
        ),
    )
    market_type: Mapped[str] = mapped_column(String(20), nullable=False)
    broker_code: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_version: Mapped[int | None] = mapped_column(Integer)
    deployment_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    runtime_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scheduler_plan_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    account_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    credential_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    operational_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recovery_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    readiness_status: Mapped[str] = mapped_column(String(30), nullable=False)
    blocking_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    warning_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    missing_requirement_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    deployment_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))


class StrategyDeploymentReadinessDecisionEntity(Base):
    __tablename__ = "strategy_deployment_readiness_decision"
    __table_args__ = (
        UniqueConstraint("deployment_readiness_package_id", name="uq_deploy_readiness_decision_package"),
        {"schema": "trading"},
    )

    deployment_readiness_decision_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    deployment_readiness_package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment_readiness_package.deployment_readiness_package_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_decision_package",
        ),
        nullable=False,
    )
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_decision_strategy_definition",
        ),
        nullable=False,
    )
    runtime_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    checklist_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    acknowledged_warnings_payload: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    same_actor_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decided_by: Mapped[str] = mapped_column(String(100), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deployment_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)


class StrategyRuntimeSchedulerPlanEntity(Base):
    """실제 APScheduler Job Store가 아니다. `enabled=false`,
    `registered_to_scheduler=false`, `scheduler_job_id=NULL`로만 저장되는
    "미래 실행을 위한 계획"이다."""

    __tablename__ = "strategy_runtime_scheduler_plan"
    __table_args__ = (
        UniqueConstraint("runtime_scope_hash", "plan_version", name="uq_scheduler_plan_scope_version"),
        {"schema": "trading"},
    )

    scheduler_plan_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    runtime_registry_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registry.runtime_registry_id", ondelete="RESTRICT",
            name="fk_scheduler_plan_registry",
        ),
        nullable=False,
    )
    runtime_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduler_type: Mapped[str] = mapped_column(String(30), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False)
    market_calendar: Mapped[str] = mapped_column(String(50), nullable=False)
    cron_expression: Mapped[str | None] = mapped_column(String(100))
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    start_policy: Mapped[str] = mapped_column(String(50), nullable=False)
    stop_policy: Mapped[str] = mapped_column(String(50), nullable=False)
    market_open_offset: Mapped[int | None] = mapped_column(Integer)
    market_close_offset: Mapped[int | None] = mapped_column(Integer)
    holiday_policy: Mapped[str] = mapped_column(String(50), nullable=False)
    retry_policy_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    misfire_policy_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    concurrency_policy_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    registered_to_scheduler: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scheduler_job_id: Mapped[str | None] = mapped_column(String(100))
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategyDeploymentReadinessCommitEntity(Base):
    __tablename__ = "strategy_deployment_readiness_commit"
    __table_args__ = (
        UniqueConstraint("deployment_readiness_package_id", name="uq_deploy_readiness_commit_package"),
        UniqueConstraint("deployment_readiness_decision_id", name="uq_deploy_readiness_commit_decision"),
        UniqueConstraint("runtime_scope_hash", name="uq_deploy_readiness_commit_scope_hash"),
        {"schema": "trading"},
    )

    deployment_readiness_commit_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_commit_strategy_definition",
        ),
        nullable=False,
    )
    runtime_registration_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registration_commit.runtime_registration_commit_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_commit_registration_commit",
        ),
        nullable=False,
    )
    runtime_registry_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registry.runtime_registry_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_commit_registry",
        ),
        nullable=False,
    )
    deployment_readiness_package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment_readiness_package.deployment_readiness_package_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_commit_package",
        ),
        nullable=False,
    )
    deployment_readiness_decision_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment_readiness_decision.deployment_readiness_decision_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_commit_decision",
        ),
        nullable=False,
    )
    runtime_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_deployment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment.strategy_deployment_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_commit_deployment",
        ),
        nullable=False,
    )
    scheduler_plan_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_scheduler_plan.scheduler_plan_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_commit_scheduler_plan",
        ),
        nullable=False,
    )
    deployment_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduler_plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deployment_commit_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    committed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)


class StrategyDeploymentReadinessHistoryEntity(Base):
    __tablename__ = "strategy_deployment_readiness_history"
    __table_args__ = (
        UniqueConstraint("event_hash", name="uq_deploy_readiness_history_event_hash"),
        {"schema": "trading"},
    )

    history_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_deploy_readiness_history_strategy_definition",
        ),
        nullable=False,
    )
    runtime_scope_hash: Mapped[str | None] = mapped_column(String(64))
    deployment_id: Mapped[int | None] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(40))
    current_status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index(
    "ix_deploy_readiness_package_strategy_definition",
    StrategyDeploymentReadinessPackageEntity.strategy_definition_id,
)
Index(
    "ix_deploy_readiness_package_registration_commit",
    StrategyDeploymentReadinessPackageEntity.runtime_registration_commit_id,
)
Index(
    "ux_deploy_readiness_package_idempotency_key",
    StrategyDeploymentReadinessPackageEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyDeploymentReadinessPackageEntity.idempotency_key.is_not(None),
)
Index(
    "ux_deploy_readiness_decision_idempotency_key",
    StrategyDeploymentReadinessDecisionEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyDeploymentReadinessDecisionEntity.idempotency_key.is_not(None),
)
Index(
    "ix_deploy_readiness_commit_strategy_definition",
    StrategyDeploymentReadinessCommitEntity.strategy_definition_id,
)
Index(
    "ux_deploy_readiness_commit_idempotency_key",
    StrategyDeploymentReadinessCommitEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyDeploymentReadinessCommitEntity.idempotency_key.is_not(None),
)
Index(
    "ix_scheduler_plan_runtime_registry",
    StrategyRuntimeSchedulerPlanEntity.runtime_registry_id,
)
Index(
    "ix_deploy_readiness_history_strategy_definition",
    StrategyDeploymentReadinessHistoryEntity.strategy_definition_id,
)
Index(
    "ix_deploy_readiness_history_occurred_at",
    StrategyDeploymentReadinessHistoryEntity.occurred_at,
)
