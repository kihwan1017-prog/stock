"""STEP 12-20 — Operation Readiness Certification (Package / Decision /
Commit / History).

READY_TO_START(§ STEP12-19)까지 도달한 Deployment를 대상으로 Strategy/
Promotion/Activation/Runtime Registration/Deployment/Scheduler Plan/
Credential/Risk/Trading Flag/Kill Switch/Recovery/Account/Runtime Scope/
Deployment Scope/History/Audit — 15개 영역을 하나의 Certification으로
묶어 최종 운영 준비 상태(`READY_TO_OPERATE`)를 확정한다. 이 STEP
어디에서도 Runtime을 시작하거나 Scheduler에 Job을 실제로 등록하거나
Broker에 연결하지 않는다.

핵심 도메인 결정 — 기존 `trading.strategy_deployment`(§ STEP12-19에서
`READY_TO_START`로 확정된 바로 그 행)를 그대로 재사용해 `status_code`만
`READY_TO_OPERATE`(신규 추가값, `models.py`)로 한 단계 더 전진시킨다.
새로운 Deployment 행을 만들지 않는다 — Certification은 이미 존재하는
Deployment Scope에 대한 "최종 검증 완료" 표시일 뿐이다."""

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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base

READINESS_STATUS_READY = "READY_FOR_OPERATION"
READINESS_STATUS_BLOCKED = "BLOCKED"

OPERATION_DECISION_APPROVE = "APPROVE_OPERATION"
OPERATION_DECISION_REQUEST_CHANGES = "REQUEST_OPERATION_CHANGES"
OPERATION_DECISION_REJECT = "REJECT_OPERATION"
OPERATION_DECISION_TYPES = frozenset(
    {OPERATION_DECISION_APPROVE, OPERATION_DECISION_REQUEST_CHANGES, OPERATION_DECISION_REJECT}
)


class StrategyOperationReadinessPackageEntity(Base):
    __tablename__ = "strategy_operation_readiness_package"
    __table_args__ = ({"schema": "trading"},)

    operation_readiness_package_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_op_readiness_package_strategy_definition",
        ),
        nullable=False,
    )
    deployment_readiness_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment_readiness_commit.deployment_readiness_commit_id", ondelete="RESTRICT",
            name="fk_op_readiness_package_deployment_commit",
        ),
        nullable=False,
    )
    runtime_registration_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registration_commit.runtime_registration_commit_id", ondelete="RESTRICT",
            name="fk_op_readiness_package_registration_commit",
        ),
        nullable=False,
    )
    runtime_registry_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registry.runtime_registry_id", ondelete="RESTRICT",
            name="fk_op_readiness_package_registry",
        ),
        nullable=False,
    )
    strategy_deployment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment.strategy_deployment_id", ondelete="RESTRICT",
            name="fk_op_readiness_package_deployment",
        ),
        nullable=False,
    )
    scheduler_plan_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_scheduler_plan.scheduler_plan_id", ondelete="RESTRICT",
            name="fk_op_readiness_package_scheduler_plan",
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
            name="fk_op_readiness_package_user_broker_account",
        ),
    )
    target_paper_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id", ondelete="RESTRICT",
            name="fk_op_readiness_package_paper_account",
        ),
    )
    market_type: Mapped[str] = mapped_column(String(20), nullable=False)
    broker_code: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_version: Mapped[int | None] = mapped_column(BigInteger)

    strategy_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    promotion_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    activation_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    runtime_registration_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    deployment_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scheduler_plan_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    credential_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    trading_flag_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    kill_switch_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recovery_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    runtime_scope_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    deployment_scope_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    history_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    audit_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    readiness_status: Mapped[str] = mapped_column(String(30), nullable=False)
    blocking_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    warning_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    missing_requirement_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    certification_areas_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    operation_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))


class StrategyOperationReadinessDecisionEntity(Base):
    __tablename__ = "strategy_operation_readiness_decision"
    __table_args__ = (
        UniqueConstraint("operation_readiness_package_id", name="uq_op_readiness_decision_package"),
        {"schema": "trading"},
    )

    operation_readiness_decision_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    operation_readiness_package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_operation_readiness_package.operation_readiness_package_id", ondelete="RESTRICT",
            name="fk_op_readiness_decision_package",
        ),
        nullable=False,
    )
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_op_readiness_decision_strategy_definition",
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
    operation_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)


class StrategyOperationReadinessCommitEntity(Base):
    __tablename__ = "strategy_operation_readiness_commit"
    __table_args__ = (
        UniqueConstraint("operation_readiness_package_id", name="uq_op_readiness_commit_package"),
        UniqueConstraint("operation_readiness_decision_id", name="uq_op_readiness_commit_decision"),
        UniqueConstraint("runtime_scope_hash", name="uq_op_readiness_commit_scope_hash"),
        {"schema": "trading"},
    )

    operation_readiness_commit_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_op_readiness_commit_strategy_definition",
        ),
        nullable=False,
    )
    deployment_readiness_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment_readiness_commit.deployment_readiness_commit_id", ondelete="RESTRICT",
            name="fk_op_readiness_commit_deployment_commit",
        ),
        nullable=False,
    )
    runtime_registration_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registration_commit.runtime_registration_commit_id", ondelete="RESTRICT",
            name="fk_op_readiness_commit_registration_commit",
        ),
        nullable=False,
    )
    runtime_registry_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registry.runtime_registry_id", ondelete="RESTRICT",
            name="fk_op_readiness_commit_registry",
        ),
        nullable=False,
    )
    strategy_deployment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment.strategy_deployment_id", ondelete="RESTRICT",
            name="fk_op_readiness_commit_deployment",
        ),
        nullable=False,
    )
    scheduler_plan_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_scheduler_plan.scheduler_plan_id", ondelete="RESTRICT",
            name="fk_op_readiness_commit_scheduler_plan",
        ),
        nullable=False,
    )
    operation_readiness_package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_operation_readiness_package.operation_readiness_package_id", ondelete="RESTRICT",
            name="fk_op_readiness_commit_package",
        ),
        nullable=False,
    )
    operation_readiness_decision_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_operation_readiness_decision.operation_readiness_decision_id", ondelete="RESTRICT",
            name="fk_op_readiness_commit_decision",
        ),
        nullable=False,
    )
    runtime_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_commit_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    committed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)


class StrategyOperationReadinessHistoryEntity(Base):
    __tablename__ = "strategy_operation_readiness_history"
    __table_args__ = (
        UniqueConstraint("event_hash", name="uq_op_readiness_history_event_hash"),
        {"schema": "trading"},
    )

    history_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_op_readiness_history_strategy_definition",
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
    "ix_op_readiness_package_strategy_definition",
    StrategyOperationReadinessPackageEntity.strategy_definition_id,
)
Index(
    "ix_op_readiness_package_deployment_commit",
    StrategyOperationReadinessPackageEntity.deployment_readiness_commit_id,
)
Index(
    "ux_op_readiness_package_idempotency_key",
    StrategyOperationReadinessPackageEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyOperationReadinessPackageEntity.idempotency_key.is_not(None),
)
Index(
    "ux_op_readiness_decision_idempotency_key",
    StrategyOperationReadinessDecisionEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyOperationReadinessDecisionEntity.idempotency_key.is_not(None),
)
Index(
    "ix_op_readiness_commit_strategy_definition",
    StrategyOperationReadinessCommitEntity.strategy_definition_id,
)
Index(
    "ux_op_readiness_commit_idempotency_key",
    StrategyOperationReadinessCommitEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyOperationReadinessCommitEntity.idempotency_key.is_not(None),
)
Index(
    "ix_op_readiness_history_strategy_definition",
    StrategyOperationReadinessHistoryEntity.strategy_definition_id,
)
Index(
    "ix_op_readiness_history_occurred_at",
    StrategyOperationReadinessHistoryEntity.occurred_at,
)
