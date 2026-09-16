"""STEP 12-3 — Strategy Draft Approval ORM.

Hard Delete 금지 — FK는 History/Provenance 보존 원칙에 따라 RESTRICT를
사용한다. `strategy_definition_id`는 승인(APPROVED) 성공 시에만 채워지는
nullable FK다(REJECTED 결정은 Strategy Definition을 만들지 않는다).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyDraftApprovalEntity(Base):
    __tablename__ = "strategy_draft_approval"
    __table_args__ = (
        # 동일 Draft에 대해 활성(APPROVED) 결정은 1개만 허용.
        Index(
            "ux_ai_sda_approval_active_draft",
            "draft_id",
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
        ),
        # 동일 Strategy Request에 대해서도 활성(APPROVED) 결정은 1개만
        # 허용한다 — 새 Draft가 승인되면 이전 활성 결정은 SUPERSEDED로
        # 전이시킨 뒤에만 새 행을 APPROVED로 만든다(서비스 레이어에서 보장).
        Index(
            "ux_ai_sda_approval_active_request",
            "strategy_request_id",
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
        ),
        UniqueConstraint(
            "draft_id", "idempotency_key", name="uq_ai_sda_approval_idempotency"
        ),
        Index("ix_ai_sda_approval_draft", "draft_id"),
        Index("ix_ai_sda_approval_request", "strategy_request_id"),
        Index("ix_ai_sda_approval_status", "status"),
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','REVOKED','SUPERSEDED')",
            name="ck_ai_sda_approval_status",
        ),
        CheckConstraint(
            "length(reason) >= 1", name="ck_ai_sda_approval_reason_len"
        ),
        {"schema": "ai"},
    )

    approval_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_draft.draft_id",
            ondelete="RESTRICT",
            name="fk_ai_sda_approval_draft",
        ),
        nullable=False,
    )
    strategy_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_request.strategy_request_id",
            ondelete="RESTRICT",
            name="fk_ai_sda_approval_request",
        ),
        nullable=False,
    )
    candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_lifecycle.candidate_id",
            ondelete="RESTRICT",
            name="fk_ai_sda_approval_candidate",
        ),
        nullable=False,
    )
    strategy_definition_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_ai_sda_approval_definition",
        ),
    )
    generation_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_draft_generation_run.generation_run_id",
            ondelete="RESTRICT",
            name="fk_ai_sda_approval_run",
        ),
    )
    generation_attempt_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_draft_generation_attempt.generation_attempt_id",
            ondelete="RESTRICT",
            name="fk_ai_sda_approval_attempt",
        ),
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING"
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # 결정 시점 Snapshot(§8) — Draft가 이후 REGENERATED/ARCHIVED되거나
    # Candidate가 바뀌어도 승인 당시 근거를 재현할 수 있도록 보존한다.
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_fingerprint_at_approval: Mapped[str | None] = mapped_column(String(64))
    candidate_provenance_fingerprint: Mapped[str | None] = mapped_column(String(64))
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    draft_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_hash: Mapped[str | None] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)

    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(100), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    revoked_reason: Mapped[str | None] = mapped_column(String(1000))
    revoked_by: Mapped[str | None] = mapped_column(String(100))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StrategyDraftApprovalHistoryEntity(Base):
    __tablename__ = "strategy_draft_approval_history"
    __table_args__ = {"schema": "ai"}

    history_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    approval_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_draft_approval.approval_id",
            ondelete="RESTRICT",
            name="fk_ai_sda_approval_hist_approval",
        ),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(1000))
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    draft_version: Mapped[int | None] = mapped_column(Integer)
    draft_revision: Mapped[int | None] = mapped_column(Integer)
    strategy_definition_id: Mapped[int | None] = mapped_column(BigInteger)
    metadata_hash: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
