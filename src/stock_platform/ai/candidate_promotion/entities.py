"""STEP 11-12 — Candidate Promotion Gateway ORM.

Safety: CandidateRun/Result INSERT는 Commit 트랜잭션에서만 (service).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AICandidatePromotionRequestEntity(Base):
    __tablename__ = "candidate_promotion_request"
    __table_args__ = (
        {"schema": "ai"},
    )

    promotion_request_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    promotion_key: Mapped[str] = mapped_column(String(220), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    queue_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_recommendation_queue.queue_id",
            ondelete="RESTRICT",
            name="fk_ai_cand_prom_req_queue",
        ),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    market_type: Mapped[str] = mapped_column(String(40), nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    promotion_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="DRAFT"
    )
    queue_decision_snapshot: Mapped[str | None] = mapped_column(String(40))
    queue_version_snapshot: Mapped[int | None] = mapped_column(Integer)
    source_result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_bundle_hash: Mapped[str | None] = mapped_column(String(64))
    eligibility_version: Mapped[str | None] = mapped_column(String(40))
    mapping_version: Mapped[str] = mapped_column(String(40), nullable=False)
    score_formula_version: Mapped[str] = mapped_column(String(40), nullable=False)
    warning_conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    requested_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dry_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    final_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    candidate_run_id: Mapped[int | None] = mapped_column(BigInteger)
    candidate_result_id: Mapped[int | None] = mapped_column(BigInteger)
    commit_idempotency_key: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message_sanitized: Mapped[str | None] = mapped_column(String(2000))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AICandidatePromotionValidationEntity(Base):
    __tablename__ = "candidate_promotion_validation"
    __table_args__ = {"schema": "ai"}

    validation_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    promotion_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_promotion_request.promotion_request_id",
            ondelete="CASCADE",
            name="fk_ai_cand_prom_val_request",
        ),
        nullable=False,
    )
    validation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    check_code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_value_hash: Mapped[str | None] = mapped_column(String(64))
    actual_value_hash: Mapped[str | None] = mapped_column(String(64))
    message_sanitized: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidatePromotionDryRunEntity(Base):
    __tablename__ = "candidate_promotion_dry_run"
    __table_args__ = {"schema": "ai"}

    dry_run_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    promotion_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_promotion_request.promotion_request_id",
            ondelete="CASCADE",
            name="fk_ai_cand_prom_dry_run_request",
        ),
        nullable=False,
    )
    dry_run_version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_run_preview_jsonb: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    candidate_result_preview_jsonb: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    conflict_summary_jsonb: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    validation_summary_jsonb: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    side_effect_summary_jsonb: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidatePromotionApprovalEntity(Base):
    __tablename__ = "candidate_promotion_approval"
    __table_args__ = {"schema": "ai"}

    approval_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    promotion_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_promotion_request.promotion_request_id",
            ondelete="CASCADE",
            name="fk_ai_cand_prom_appr_request",
        ),
        nullable=False,
    )
    approval_stage: Mapped[str] = mapped_column(String(20), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(100), nullable=False)
    approval_reason: Mapped[str | None] = mapped_column(String(500))
    warning_acknowledgements: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_result_hash_at_approval: Mapped[str | None] = mapped_column(String(64))
    evidence_bundle_hash_at_approval: Mapped[str | None] = mapped_column(String(64))
    queue_version_at_approval: Mapped[int | None] = mapped_column(Integer)
    dry_run_result_hash: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidatePromotionLinkEntity(Base):
    __tablename__ = "candidate_promotion_link"
    __table_args__ = {"schema": "ai"}

    link_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    promotion_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_promotion_request.promotion_request_id",
            ondelete="RESTRICT",
            name="fk_ai_cand_prom_link_request",
        ),
        nullable=False,
    )
    queue_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_recommendation_queue.queue_id",
            ondelete="RESTRICT",
            name="fk_ai_cand_prom_link_queue",
        ),
        nullable=False,
    )
    candidate_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    candidate_result_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    candidate_result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    promoted_by: Mapped[str] = mapped_column(String(100), nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    rollback_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="NONE"
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rollback_reason: Mapped[str | None] = mapped_column(String(500))


class AICandidatePromotionHistoryEntity(Base):
    __tablename__ = "candidate_promotion_history"
    __table_args__ = {"schema": "ai"}

    history_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    promotion_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_promotion_request.promotion_request_id",
            ondelete="CASCADE",
            name="fk_ai_cand_prom_hist_request",
        ),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(500))
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
