"""STEP 11-13 — Candidate Lifecycle ORM.

candidate_id = strategy.candidate_result.result_id (FK RESTRICT, no hard delete).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AICandidateLifecycleEntity(Base):
    __tablename__ = "candidate_lifecycle"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_ai_cand_lifecycle_candidate"),
        {"schema": "ai"},
    )

    lifecycle_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "strategy.candidate_result.result_id",
            ondelete="RESTRICT",
            name="fk_ai_cand_lifecycle_result",
        ),
        nullable=False,
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="PROMOTED"
    )
    health_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="UNKNOWN"
    )
    lifecycle_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    source_fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_changed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    revalidation_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    expiration_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_revalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    status_reason_code: Mapped[str | None] = mapped_column(String(80))
    status_reason_message: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[str] = mapped_column(String(100), nullable=False)


class AICandidateLifecycleHistoryEntity(Base):
    __tablename__ = "candidate_lifecycle_history"
    __table_args__ = {"schema": "ai"}

    history_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_lifecycle.candidate_id",
            ondelete="CASCADE",
            name="fk_ai_cand_lifecycle_hist_candidate",
        ),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_lifecycle_status: Mapped[str | None] = mapped_column(String(40))
    new_lifecycle_status: Mapped[str | None] = mapped_column(String(40))
    previous_health_status: Mapped[str | None] = mapped_column(String(40))
    new_health_status: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(500))
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateProvenanceSnapshotEntity(Base):
    __tablename__ = "candidate_provenance_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            name="uq_ai_cand_prov_snapshot_candidate",
        ),
        {"schema": "ai"},
    )

    snapshot_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_lifecycle.candidate_id",
            ondelete="CASCADE",
            name="fk_ai_cand_prov_snapshot_candidate",
        ),
        nullable=False,
    )
    promotion_request_id: Mapped[int | None] = mapped_column(BigInteger)
    promotion_link_id: Mapped[int | None] = mapped_column(BigInteger)
    queue_id: Mapped[int | None] = mapped_column(BigInteger)
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[int | None] = mapped_column(BigInteger)
    source_result_hash: Mapped[str | None] = mapped_column(String(64))
    evidence_bundle_hash: Mapped[str | None] = mapped_column(String(64))
    queue_version_snapshot: Mapped[int | None] = mapped_column(Integer)
    candidate_result_hash: Mapped[str | None] = mapped_column(String(64))
    combined_source_fingerprint: Mapped[str | None] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="prov-1.0.0"
    )
    source_graph: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateRevalidationEntity(Base):
    __tablename__ = "candidate_revalidation"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "revalidation_key",
            name="uq_ai_cand_revalidation_key",
        ),
        {"schema": "ai"},
    )

    revalidation_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_lifecycle.candidate_id",
            ondelete="CASCADE",
            name="fk_ai_cand_revalidation_candidate",
        ),
        nullable=False,
    )
    revalidation_key: Mapped[str] = mapped_column(String(220), nullable=False)
    revalidation_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="REQUESTED"
    )
    expected_fingerprint: Mapped[str | None] = mapped_column(String(64))
    actual_fingerprint: Mapped[str | None] = mapped_column(String(64))
    fingerprint_match: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    warnings: Mapped[list[Any] | None] = mapped_column(JSONB)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    completed_by: Mapped[str | None] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(String(500))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateRevocationEntity(Base):
    __tablename__ = "candidate_revocation"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "revocation_key",
            name="uq_ai_cand_revocation_key",
        ),
        {"schema": "ai"},
    )

    revocation_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_lifecycle.candidate_id",
            ondelete="CASCADE",
            name="fk_ai_cand_revocation_candidate",
        ),
        nullable=False,
    )
    revocation_key: Mapped[str] = mapped_column(String(220), nullable=False)
    revocation_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="REQUESTED"
    )
    blocked_reasons: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(String(500))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AICandidateSupersessionEntity(Base):
    __tablename__ = "candidate_supersession"
    __table_args__ = (
        CheckConstraint(
            "previous_candidate_id <> replacement_candidate_id",
            name="ck_ai_cand_supersession_distinct",
        ),
        {"schema": "ai"},
    )

    supersession_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    previous_candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_lifecycle.candidate_id",
            ondelete="RESTRICT",
            name="fk_ai_cand_supersession_previous",
        ),
        nullable=False,
    )
    replacement_candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.candidate_lifecycle.candidate_id",
            ondelete="RESTRICT",
            name="fk_ai_cand_supersession_replacement",
        ),
        nullable=False,
    )
    supersession_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )
    reason: Mapped[str | None] = mapped_column(String(500))
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
