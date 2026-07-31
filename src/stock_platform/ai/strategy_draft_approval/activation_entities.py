"""STEP 12-17 — Strategy Activation Review Package / Decision / Commit 저장.

PROMOTION_COMMITTED 상태인 Strategy Definition을 대상으로 Activation
Review(계좌·시장·브로커·리스크·운영 준비 상태 검증) → Human Activation
Decision → Activation Commit까지의 불변 기록을 저장한다. Runtime 등록/
시작, Scheduler 등록, Broker 연결, 주문 실행은 전혀 수행하지 않는다(§
STEP12-17 명세 "Activation이 의미하지 않는 것").

Promotion State 전이는 `promotion_state_entities.py`의 기존
`strategy_promotion_state`(공식 Source of Truth, 1행)와
`strategy_promotion_history`(불변 전이 기록)를 그대로 재사용한다 — 이
STEP에서 새 History 테이블을 중복 생성하지 않는다. `PROMOTION_COMMITTED
→ ACTIVATION_REVIEW → ACTIVATED` 전이만 이 테이블들에 추가로 기록된다.

세 개의 새 불변 테이블만 신설한다:
- `strategy_activation_review_package`: Decision Package와 동일한
  불변 Snapshot Report 패턴(생성 후 UPDATE 없음, 재검토는 새 Package).
- `strategy_activation_decision`: Human Decision과 동일한 불변 기록
  패턴(Package당 최종 Decision 1개, UNIQUE).
- `strategy_activation_commit`: Promotion Commit과 동일한 불변 기록
  패턴(Package/Decision당 Commit 1개, UNIQUE).
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base

# § Activation Readiness Status — 명세 §"Activation Readiness". Package는
# 불변이므로 생성 시점에는 READY_FOR_ACTIVATION_REVIEW/BLOCKED만 저장한다
# (STALE/DECIDED는 조회 시점에 동적으로 재계산되는 파생 상태이며 컬럼에
# 저장하지 않는다 — Package 자체는 절대 UPDATE되지 않는다).
ACTIVATION_READINESS_READY = "READY_FOR_ACTIVATION_REVIEW"
ACTIVATION_READINESS_BLOCKED = "BLOCKED"

# § Account Kind — 기존 `strategy_deployment/runtime_scope.py`의
# `AccountKind` 문자열 값과 동일 어휘를 재사용한다(새 어휘 발명 금지).
ACCOUNT_KIND_USER_BROKER = "USER_BROKER"
ACCOUNT_KIND_PAPER = "PAPER"
ACCOUNT_KIND_VALUES = frozenset({ACCOUNT_KIND_USER_BROKER, ACCOUNT_KIND_PAPER})

# § Execution Mode — 이번 STEP에서 실제로 검증 로직을 구현·테스트하는
# 것은 PAPER/LIVE 둘뿐이다. MOCK/DISABLED는 Enum 값만 마련해 둔다(§
# STEP12-16R에서 ACTIVATION_REVIEW 이후 상태를 Enum만 마련해 둔 것과
# 동일한 패턴).
EXECUTION_MODE_PAPER = "PAPER"
EXECUTION_MODE_LIVE = "LIVE"
EXECUTION_MODE_MOCK = "MOCK"
EXECUTION_MODE_DISABLED = "DISABLED"
EXECUTION_MODE_VALUES = frozenset(
    {EXECUTION_MODE_PAPER, EXECUTION_MODE_LIVE, EXECUTION_MODE_MOCK, EXECUTION_MODE_DISABLED}
)

# § Human Activation Decision Type.
ACTIVATION_DECISION_APPROVE = "APPROVE_ACTIVATION"
ACTIVATION_DECISION_REQUEST_CHANGES = "REQUEST_ACTIVATION_CHANGES"
ACTIVATION_DECISION_REJECT = "REJECT_ACTIVATION"
ACTIVATION_DECISION_TYPES = frozenset(
    {ACTIVATION_DECISION_APPROVE, ACTIVATION_DECISION_REQUEST_CHANGES, ACTIVATION_DECISION_REJECT}
)


class StrategyActivationReviewPackageEntity(Base):
    __tablename__ = "strategy_activation_review_package"
    __table_args__ = ({"schema": "trading"},)

    activation_review_package_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_activation_review_package_strategy_definition",
        ),
        nullable=False,
    )
    promotion_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_promotion_commit.promotion_commit_id",
            ondelete="RESTRICT",
            name="fk_activation_review_package_promotion_commit",
        ),
        nullable=False,
    )
    requested_market_type: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_broker_code: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_account_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="RESTRICT",
            name="fk_activation_review_package_user_broker_account",
        ),
    )
    requested_paper_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id",
            ondelete="RESTRICT",
            name="fk_activation_review_package_paper_account",
        ),
    )
    requested_execution_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_runtime_scope_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    requested_capital_limit: Mapped[Any | None] = mapped_column(Numeric(20, 4))
    review_note: Mapped[str | None] = mapped_column(Text)
    effective_risk_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    account_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    broker_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    operational_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    readiness_status: Mapped[str] = mapped_column(String(30), nullable=False)
    blocking_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    warning_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    missing_requirement_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    review_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)


class StrategyActivationDecisionEntity(Base):
    __tablename__ = "strategy_activation_decision"
    __table_args__ = (
        UniqueConstraint(
            "activation_review_package_id", name="uq_activation_decision_package"
        ),
        {"schema": "trading"},
    )

    activation_decision_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    activation_review_package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_activation_review_package.activation_review_package_id",
            ondelete="RESTRICT",
            name="fk_activation_decision_package",
        ),
        nullable=False,
    )
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_activation_decision_strategy_definition",
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
    activation_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)


class StrategyActivationCommitEntity(Base):
    __tablename__ = "strategy_activation_commit"
    __table_args__ = (
        UniqueConstraint("strategy_definition_id", name="uq_activation_commit_strategy_definition"),
        UniqueConstraint("activation_review_package_id", name="uq_activation_commit_package"),
        UniqueConstraint("activation_decision_id", name="uq_activation_commit_decision"),
        {"schema": "trading"},
    )

    activation_commit_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_activation_commit_strategy_definition",
        ),
        nullable=False,
    )
    promotion_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_promotion_commit.promotion_commit_id",
            ondelete="RESTRICT",
            name="fk_activation_commit_promotion_commit",
        ),
        nullable=False,
    )
    activation_review_package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_activation_review_package.activation_review_package_id",
            ondelete="RESTRICT",
            name="fk_activation_commit_package",
        ),
        nullable=False,
    )
    activation_decision_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_activation_decision.activation_decision_id",
            ondelete="RESTRICT",
            name="fk_activation_commit_decision",
        ),
        nullable=False,
    )
    target_market_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_broker_code: Mapped[str] = mapped_column(String(20), nullable=False)
    target_account_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="RESTRICT",
            name="fk_activation_commit_user_broker_account",
        ),
    )
    target_paper_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id",
            ondelete="RESTRICT",
            name="fk_activation_commit_paper_account",
        ),
    )
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    runtime_scope_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    account_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    credential_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    previous_promotion_status: Mapped[str] = mapped_column(String(30), nullable=False)
    committed_promotion_status: Mapped[str] = mapped_column(String(30), nullable=False)
    review_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    commit_reason: Mapped[str] = mapped_column(Text, nullable=False)
    confirmation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    activation_commit_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    committed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)


Index(
    "ix_activation_review_package_strategy_definition",
    StrategyActivationReviewPackageEntity.strategy_definition_id,
)
Index(
    "ix_activation_review_package_promotion_commit",
    StrategyActivationReviewPackageEntity.promotion_commit_id,
)
Index(
    "ux_activation_review_package_idempotency_key",
    StrategyActivationReviewPackageEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyActivationReviewPackageEntity.idempotency_key.is_not(None),
)
Index(
    "ux_activation_decision_idempotency_key",
    StrategyActivationDecisionEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyActivationDecisionEntity.idempotency_key.is_not(None),
)
Index(
    "ix_activation_commit_strategy_definition",
    StrategyActivationCommitEntity.strategy_definition_id,
)
Index(
    "ux_activation_commit_idempotency_key",
    StrategyActivationCommitEntity.idempotency_key,
    unique=True,
    postgresql_where=StrategyActivationCommitEntity.idempotency_key.is_not(None),
)
