"""STEP 12-18 — Runtime Registration Package / Decision / Commit / Registry.

ACTIVATED 상태의 Strategy Definition을 대상으로 계좌/시장/브로커/리스크/
운영 준비 상태를 재검증한 뒤, 관리자의 명시적 Runtime Registration
Commit으로 "Runtime에 등록 가능한 불변 구성"을 확정한다. Runtime을
실제로 시작(start)하거나 Scheduler에 등록하거나 Broker에 연결·로그인
하지 않는다 — `strategy_runtime_registry`는 `running=false`,
`enabled=false`로만 기록되는 비실행 등록 테이블이다(§ 모듈 최상단
"Runtime Registration이 의미하지 않는 것").

Strategy Promotion State/History는 STEP12-16R/17이 이미 만든 테이블을
그대로 재사용한다(ACTIVATED는 이 STEP에서 더 이상 전이시키지 않는다 —
Runtime Registration은 Promotion State 축과 별개의 새로운 "등록 여부"
개념이다). 기존 `AccountStrategyLinkEntity`/`StrategyDeploymentEntity`는
읽기 전용으로 충돌 조회에만 사용하고, Deployment는 이 STEP에서 전혀
생성하지 않는다(STEP12-19 범위).
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base

REGISTRATION_READINESS_READY = "READY_FOR_RUNTIME_REGISTRATION"
REGISTRATION_READINESS_BLOCKED = "BLOCKED"

REGISTRATION_DECISION_APPROVE = "APPROVE_RUNTIME_REGISTRATION"
REGISTRATION_DECISION_REQUEST_CHANGES = "REQUEST_RUNTIME_REGISTRATION_CHANGES"
REGISTRATION_DECISION_REJECT = "REJECT_RUNTIME_REGISTRATION"
REGISTRATION_DECISION_TYPES = frozenset(
    {REGISTRATION_DECISION_APPROVE, REGISTRATION_DECISION_REQUEST_CHANGES, REGISTRATION_DECISION_REJECT}
)

REGISTRY_STATUS_REGISTERED = "REGISTERED"


class StrategyRuntimeRegistrationPackageEntity(Base):
    __tablename__ = "strategy_runtime_registration_package"
    __table_args__ = ({"schema": "trading"},)

    runtime_registration_package_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_runtime_reg_package_strategy_definition",
        ),
        nullable=False,
    )
    activation_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_activation_commit.activation_commit_id", ondelete="RESTRICT",
            name="fk_runtime_reg_package_activation_commit",
        ),
        nullable=False,
    )
    activation_decision_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_activation_decision.activation_decision_id", ondelete="RESTRICT",
            name="fk_runtime_reg_package_activation_decision",
        ),
        nullable=False,
    )
    target_user_id: Mapped[int | None] = mapped_column(BigInteger)
    target_account_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id", ondelete="RESTRICT",
            name="fk_runtime_reg_package_user_broker_account",
        ),
    )
    target_paper_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id", ondelete="RESTRICT",
            name="fk_runtime_reg_package_paper_account",
        ),
    )
    target_market_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_broker_code: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_version: Mapped[int | None] = mapped_column(Integer)
    runtime_scope_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    runtime_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    account_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    credential_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    operational_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    activation_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    registration_readiness_status: Mapped[str] = mapped_column(String(30), nullable=False)
    blocking_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    warning_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    missing_requirement_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    registration_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))


class StrategyRuntimeRegistrationDecisionEntity(Base):
    __tablename__ = "strategy_runtime_registration_decision"
    __table_args__ = (
        UniqueConstraint("runtime_registration_package_id", name="uq_runtime_reg_decision_package"),
        {"schema": "trading"},
    )

    runtime_registration_decision_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    runtime_registration_package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registration_package.runtime_registration_package_id", ondelete="RESTRICT",
            name="fk_runtime_reg_decision_package",
        ),
        nullable=False,
    )
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_runtime_reg_decision_strategy_definition",
        ),
        nullable=False,
    )
    decision_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    checklist_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    acknowledged_warnings_payload: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    same_actor_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decided_by: Mapped[str] = mapped_column(String(100), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    registration_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)


class StrategyRuntimeRegistrationCommitEntity(Base):
    """§ STEP12-18R — `strategy_definition_id` 단독 UNIQUE를 두지 않는다
    (동일 Strategy가 서로 다른 정상 Runtime Scope — 다른 Account/User/
    Execution Mode/Version — 에 각각 등록될 수 있어야 한다). 유일성은
    `runtime_scope_hash`(및 Package/Decision 1:1 관계)로만 제한한다."""

    __tablename__ = "strategy_runtime_registration_commit"
    __table_args__ = (
        UniqueConstraint("runtime_registration_package_id", name="uq_runtime_reg_commit_package"),
        UniqueConstraint("runtime_registration_decision_id", name="uq_runtime_reg_commit_decision"),
        UniqueConstraint("runtime_scope_hash", name="uq_runtime_reg_commit_scope_hash"),
        {"schema": "trading"},
    )

    runtime_registration_commit_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_runtime_reg_commit_strategy_definition",
        ),
        nullable=False,
    )
    activation_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_activation_commit.activation_commit_id", ondelete="RESTRICT",
            name="fk_runtime_reg_commit_activation_commit",
        ),
        nullable=False,
    )
    runtime_registration_package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registration_package.runtime_registration_package_id", ondelete="RESTRICT",
            name="fk_runtime_reg_commit_package",
        ),
        nullable=False,
    )
    runtime_registration_decision_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registration_decision.runtime_registration_decision_id", ondelete="RESTRICT",
            name="fk_runtime_reg_commit_decision",
        ),
        nullable=False,
    )
    target_user_id: Mapped[int | None] = mapped_column(BigInteger)
    account_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id", ondelete="RESTRICT",
            name="fk_runtime_reg_commit_user_broker_account",
        ),
    )
    target_paper_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id", ondelete="RESTRICT",
            name="fk_runtime_reg_commit_paper_account",
        ),
    )
    market_type: Mapped[str] = mapped_column(String(20), nullable=False)
    broker_code: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_version: Mapped[int | None] = mapped_column(Integer)
    runtime_scope_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    runtime_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    account_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    credential_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    operational_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    registration_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    registration_commit_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    committed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)


class StrategyRuntimeRegistryEntity(Base):
    """비실행 Runtime Registry — `enabled=false`, `running=false`로만
    기록된다. 이 행이 존재한다고 Runtime이 실제로 동작하는 것은 전혀
    아니다(§ 모듈 docstring)."""

    __tablename__ = "strategy_runtime_registry"
    __table_args__ = (
        UniqueConstraint("runtime_scope_hash", name="uq_runtime_registry_scope_hash"),
        UniqueConstraint("runtime_registration_commit_id", name="uq_runtime_registry_commit"),
        {"schema": "trading"},
    )

    runtime_registry_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_runtime_registry_strategy_definition",
        ),
        nullable=False,
    )
    runtime_registration_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_registration_commit.runtime_registration_commit_id", ondelete="RESTRICT",
            name="fk_runtime_registry_commit",
        ),
        nullable=False,
    )
    runtime_scope_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    runtime_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[int | None] = mapped_column(Integer)
    account_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id", ondelete="RESTRICT",
            name="fk_runtime_registry_user_broker_account",
        ),
    )
    target_paper_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id", ondelete="RESTRICT",
            name="fk_runtime_registry_paper_account",
        ),
    )
    market_type: Mapped[str] = mapped_column(String(20), nullable=False)
    broker_code: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=REGISTRY_STATUS_REGISTERED)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    registered_by: Mapped[str] = mapped_column(String(100), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategyRuntimeRegistrationHistoryEntity(Base):
    """§ STEP12-18R — 영속 불변 History(INSERT ONLY, UPDATE/DELETE API
    없음). Package/Decision/Commit 각각이 생성되는 바로 그 Transaction
    안에서 자신의 이벤트를 함께 저장한다(동적 합성이 아니다)."""

    __tablename__ = "strategy_runtime_registration_history"
    __table_args__ = (
        UniqueConstraint("event_hash", name="uq_runtime_reg_history_event_hash"),
        {"schema": "trading"},
    )

    history_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id", ondelete="RESTRICT",
            name="fk_runtime_reg_history_strategy_definition",
        ),
        nullable=False,
    )
    runtime_scope_hash: Mapped[str | None] = mapped_column(String(64))
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
    "ix_runtime_reg_package_strategy_definition",
    StrategyRuntimeRegistrationPackageEntity.strategy_definition_id,
)
Index(
    "ix_runtime_reg_package_activation_commit",
    StrategyRuntimeRegistrationPackageEntity.activation_commit_id,
)
Index(
    "ux_runtime_reg_package_idempotency_key",
    StrategyRuntimeRegistrationPackageEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyRuntimeRegistrationPackageEntity.idempotency_key.is_not(None),
)
Index(
    "ux_runtime_reg_decision_idempotency_key",
    StrategyRuntimeRegistrationDecisionEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyRuntimeRegistrationDecisionEntity.idempotency_key.is_not(None),
)
Index(
    "ix_runtime_reg_commit_strategy_definition",
    StrategyRuntimeRegistrationCommitEntity.strategy_definition_id,
)
Index(
    "ux_runtime_reg_commit_idempotency_key",
    StrategyRuntimeRegistrationCommitEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyRuntimeRegistrationCommitEntity.idempotency_key.is_not(None),
)
Index(
    "ix_runtime_registry_strategy_definition",
    StrategyRuntimeRegistryEntity.strategy_definition_id,
)
Index(
    "ix_runtime_reg_history_strategy_definition",
    StrategyRuntimeRegistrationHistoryEntity.strategy_definition_id,
)
Index(
    "ix_runtime_reg_history_occurred_at",
    StrategyRuntimeRegistrationHistoryEntity.occurred_at,
)
