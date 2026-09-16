"""STEP 12-1 — Strategy Request ORM.

candidate_id = ai.candidate_lifecycle.candidate_id (FK RESTRICT).
Hard Delete 금지 — 상태 변경만 허용, 상태 이력은 strategy_request_history에
별도 보존한다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyRequestEntity(Base):
    __tablename__ = "strategy_request"
    __table_args__ = (
        # 동일 Candidate에 대해 PENDING_REVIEW(활성) 상태 요청은 1개만 허용.
        # 승인/반려/취소된 요청은 제외돼 재요청이 가능하다.
        Index(
            "ux_ai_strategy_request_candidate_active",
            "candidate_id",
            unique=True,
            postgresql_where=text("status = 'PENDING_REVIEW'"),
        ),
        Index("ix_ai_strategy_request_user", "user_id"),
        Index("ix_ai_strategy_request_status", "status"),
        {"schema": "ai"},
    )

    strategy_request_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_lifecycle.candidate_id",
            ondelete="RESTRICT",
            name="fk_ai_strategy_request_candidate",
        ),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="RESTRICT",
            name="fk_ai_strategy_request_user",
        ),
        nullable=False,
    )
    reviewer_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="RESTRICT",
            name="fk_ai_strategy_request_reviewer",
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING_REVIEW"
    )
    # 요청 시점 candidate_lifecycle_status 스냅샷 — 심사 시점 근거 보존용
    # (candidate 상태가 이후 바뀌어도 요청 당시 근거를 추적 가능하게 함).
    candidate_lifecycle_status_snapshot: Mapped[str] = mapped_column(
        String(40), nullable=False
    )
    # 승인(approve) 재검증 시점 스냅샷 — STEP12-1A. 요청 생성 시점과 승인
    # 시점 사이에 Candidate 상태/근거가 바뀌었는지 STEP12-2에서 추적할 수
    # 있도록 approve() 성공 시에만 채워진다(과거 행/미승인 요청은 NULL).
    candidate_status_at_review: Mapped[str | None] = mapped_column(String(40))
    candidate_fingerprint_at_review: Mapped[str | None] = mapped_column(String(64))
    request_note: Mapped[str | None] = mapped_column(String(1000))
    review_note: Mapped[str | None] = mapped_column(String(1000))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StrategyRequestHistoryEntity(Base):
    __tablename__ = "strategy_request_history"
    __table_args__ = {"schema": "ai"}

    history_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    strategy_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_request.strategy_request_id",
            ondelete="CASCADE",
            name="fk_ai_strategy_request_hist_request",
        ),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(1000))
    # 이력 테이블은 candidate_lifecycle_history/candidate_promotion_history와
    # 동일하게 actor를 문자열 라벨로 남긴다(불변 감사 기록 — FK 대상 계정이
    # 이후 사라지거나 바뀌어도 당시 행위자 표기가 보존되어야 하므로).
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
