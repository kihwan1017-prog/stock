"""STEP 12-2-1 — Strategy Draft ORM.

strategy_request_id = ai.strategy_request.strategy_request_id (FK RESTRICT).
Hard Delete 금지 — 상태 변경만 허용, 상태 이력은 strategy_draft_history에
별도 보존한다(RESTRICT — STEP12-1A에서 CASCADE의 감사 이력 보존 원칙 상충
문제를 확인해 처음부터 RESTRICT로 설계).

owner(요청자) 식별은 별도 컬럼을 두지 않고 strategy_request_id ->
strategy_request.user_id로 파생 조회한다(중복 데이터 방지 — strategy_request가
이미 user_id의 단일 진실 공급원).
"""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyDraftEntity(Base):
    __tablename__ = "strategy_draft"
    __table_args__ = (
        UniqueConstraint(
            "strategy_request_id",
            "version",
            "revision",
            name="uq_ai_strategy_draft_request_version_revision",
        ),
        # 동일 Strategy Request에 대해 DRAFT(활성) 행은 1개만 허용.
        Index(
            "ux_ai_strategy_draft_request_active",
            "strategy_request_id",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
        ),
        Index("ix_ai_strategy_draft_request", "strategy_request_id"),
        Index("ix_ai_strategy_draft_status", "status"),
        {"schema": "ai"},
    )

    draft_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_request.strategy_request_id",
            ondelete="RESTRICT",
            name="fk_ai_strategy_draft_request",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(2000))
    entry_rule: Mapped[str | None] = mapped_column(Text)
    exit_rule: Mapped[str | None] = mapped_column(Text)
    stop_loss_rule: Mapped[str | None] = mapped_column(Text)
    take_profit_rule: Mapped[str | None] = mapped_column(Text)
    position_sizing_rule: Mapped[str | None] = mapped_column(Text)
    timeframe: Mapped[str] = mapped_column(String(20), nullable=False)
    market_type: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    indicator_configuration: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # AI 미구현(STEP12-2-2 이후) — 현재는 관리자가 참고용으로 남기는
    # 메타데이터일 뿐, 이 STEP에서 이 값으로 실제 AI 호출을 하지 않는다.
    llm_provider: Mapped[str | None] = mapped_column(String(50))
    llm_model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(40))

    # 승인 시점 Candidate fingerprint(strategy_request.candidate_fingerprint_at_review)
    # 복사본 — 요청/심사/초안 3단계 근거 체인을 추적하기 위한 provenance.
    candidate_fingerprint: Mapped[str | None] = mapped_column(String(64))

    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StrategyDraftHistoryEntity(Base):
    __tablename__ = "strategy_draft_history"
    __table_args__ = {"schema": "ai"}

    history_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_draft.draft_id",
            ondelete="RESTRICT",
            name="fk_ai_strategy_draft_hist_draft",
        ),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str | None] = mapped_column(String(20))
    previous_version: Mapped[int | None] = mapped_column(Integer)
    new_version: Mapped[int | None] = mapped_column(Integer)
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    new_revision: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(1000))
    # strategy_request_history와 동일하게 actor를 문자열 라벨로 남긴다
    # (불변 감사 기록 — 계정이 이후 사라지거나 바뀌어도 표기 보존).
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
