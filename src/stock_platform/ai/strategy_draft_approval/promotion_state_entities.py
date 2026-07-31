"""STEP 12-16R — Strategy Promotion State & History 저장.

STEP12-16 재작업 핵심 사유: 기존 구현은 Promotion Commit 행에
`committed_lifecycle_status="PROMOTED"`를 "기록"만 했을 뿐, 실제로
전이시키는 별도 상태 축이 없었다(사실상 Promotion Event Snapshot
저장까지만 수행). 이 모듈이 그 공식 Source of Truth(현재 상태 1개 +
불변 History)를 추가한다.

핵심 도메인 결정(중요): `ai.candidate_lifecycle.lifecycle_status`의
`PROMOTED`는 Candidate가 Strategy Request 생성 자격을 얻는 훨씬 이른
단계의 의미로 이미 확립돼 있다(STEP11). 이 모듈의 Strategy Promotion
State는 완전히 별개의 상태 축이며, Candidate Lifecycle을 절대 WRITE
하지 않는다(선행조건 검증에서 읽기만 함, § promotion_commit.py)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base

# Strategy Promotion State Enum(문서화된 값) — 이번 STEP에서 실제로
# 전이시키는 것은 NOT_PROMOTED -> PROMOTION_COMMITTED 뿐이다.
# ACTIVATION_REVIEW/ACTIVATED/REVOKED/SUPERSEDED/ARCHIVED는 향후 STEP이
# 사용할 수 있도록 값만 마련해 둔다(이번 STEP에서 전이하지 않음).
PROMOTION_STATE_NOT_PROMOTED = "NOT_PROMOTED"
PROMOTION_STATE_PROMOTION_COMMITTED = "PROMOTION_COMMITTED"
PROMOTION_STATE_ACTIVATION_REVIEW = "ACTIVATION_REVIEW"
PROMOTION_STATE_ACTIVATED = "ACTIVATED"
PROMOTION_STATE_REVOKED = "REVOKED"
PROMOTION_STATE_SUPERSEDED = "SUPERSEDED"
PROMOTION_STATE_ARCHIVED = "ARCHIVED"

PROMOTION_STATE_VALUES = frozenset(
    {
        PROMOTION_STATE_NOT_PROMOTED,
        PROMOTION_STATE_PROMOTION_COMMITTED,
        PROMOTION_STATE_ACTIVATION_REVIEW,
        PROMOTION_STATE_ACTIVATED,
        PROMOTION_STATE_REVOKED,
        PROMOTION_STATE_SUPERSEDED,
        PROMOTION_STATE_ARCHIVED,
    }
)


class StrategyPromotionStateEntity(Base):
    """Strategy Definition의 공식 현재 Promotion State(1 Strategy = 1
    행). Promotion Commit과 같은 Transaction에서만 전이하는 전용
    Domain Transition Service(`promotion_commit.py`)를 통해서만
    변경한다 — 일반 CRUD/Admin API로 직접 UPDATE하지 않는다."""

    __tablename__ = "strategy_promotion_state"
    __table_args__ = (
        UniqueConstraint("strategy_definition_id", name="uq_promotion_state_strategy_definition"),
        {"schema": "trading"},
    )

    strategy_promotion_state_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_promotion_state_strategy_definition",
        ),
        nullable=False,
    )
    current_status: Mapped[str] = mapped_column(String(30), nullable=False)
    status_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_promotion_commit_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_promotion_commit.promotion_commit_id",
            ondelete="RESTRICT",
            name="fk_promotion_state_current_commit",
        ),
    )
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(100), nullable=False)


class StrategyPromotionHistoryEntity(Base):
    """Strategy Promotion State 전이의 불변 History(INSERT ONLY — UPDATE/
    DELETE API 없음). 동일 Promotion Commit에 동일 전이(new_status) 행은
    1개만 허용한다(UNIQUE 제약)."""

    __tablename__ = "strategy_promotion_history"
    __table_args__ = (
        UniqueConstraint(
            "promotion_commit_id", "new_status", name="uq_promotion_history_commit_status"
        ),
        Index("ix_promotion_history_strategy_definition", "strategy_definition_id"),
        Index("ix_promotion_history_occurred_at", "occurred_at"),
        Index("ux_promotion_history_event_hash", "event_hash", unique=True),
        {"schema": "trading"},
    )

    promotion_history_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_promotion_history_strategy_definition",
        ),
        nullable=False,
    )
    promotion_commit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_promotion_commit.promotion_commit_id",
            ondelete="RESTRICT",
            name="fk_promotion_history_commit",
        ),
        nullable=False,
    )
    previous_status: Mapped[str] = mapped_column(String(30), nullable=False)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    transition_reason: Mapped[str] = mapped_column(Text, nullable=False)
    human_decision_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    decision_package_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
