"""ORM — Profitability Improvement Shadow Lab V1 (research only)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.constants import (
    RULE_VERSION,
    STATUS_ACTIVE,
    STATUS_PENDING_OUTCOME,
)


class UpbitProfitabilityCandidateRefreshEntity(Base):
    """Candidate refresh observation — Lab A (forward outcomes 별도 갱신)."""

    __tablename__ = "upbit_profitability_candidate_refresh"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "scanner_run_id",
            name="uq_pislab_cand_refresh_run",
        ),
        Index("ix_pislab_cand_refresh_uba_obs", "user_broker_account_id", "observed_at"),
        {"schema": "operation"},
    )

    refresh_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    scanner_run_id: Mapped[str] = mapped_column(String(80), nullable=False)
    selection_id: Mapped[int | None] = mapped_column(BigInteger)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rule_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{RULE_VERSION}'")
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_PENDING_OUTCOME}'")
    )
    universe_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    rankings_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    outcomes_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UpbitProfitabilityExitEnrollmentEntity(Base):
    """Exit V4 enrollment — binding당 1 (REAL baseline)."""

    __tablename__ = "upbit_profitability_exit_enrollment"
    __table_args__ = (
        UniqueConstraint("binding_id", name="uq_pislab_exit_enrollment_binding"),
        Index("ix_pislab_exit_enroll_uba", "user_broker_account_id"),
        Index("ix_pislab_exit_enroll_status", "status"),
        {"schema": "operation"},
    )

    enrollment_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    binding_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_order_id: Mapped[int | None] = mapped_column(BigInteger)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    entry_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    entry_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rule_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{RULE_VERSION}'")
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_ACTIVE}'")
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    real_exit_reason: Mapped[str | None] = mapped_column(String(64))
    real_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    real_exit_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    real_gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    real_fees: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    real_net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    real_holding_seconds: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    path_state_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UpbitProfitabilityExitVariantEntity(Base):
    """Exit V4 variant observation — REAL과 분리."""

    __tablename__ = "upbit_profitability_exit_variant"
    __table_args__ = (
        UniqueConstraint(
            "binding_id", "variant_id", name="uq_pislab_exit_variant_binding"
        ),
        Index("ix_pislab_exit_variant_enroll", "enrollment_id"),
        {"schema": "operation"},
    )

    variant_row_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    enrollment_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    binding_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variant_id: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_ACTIVE}'")
    )
    shadow_exit_reason: Mapped[str | None] = mapped_column(String(64))
    shadow_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shadow_exit_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    shadow_gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    shadow_fees: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    shadow_net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    shadow_holding_seconds: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    shadow_mfe_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    net_delta: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    defer_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    state_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UpbitProfitabilityReentryEventEntity(Base):
    """Reentry anti-churn observation — Lab C."""

    __tablename__ = "upbit_profitability_reentry_event"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "entry_order_id",
            name="uq_pislab_reentry_entry_order",
        ),
        Index("ix_pislab_reentry_uba_obs", "user_broker_account_id", "reentry_at"),
        {"schema": "operation"},
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    prior_exit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prior_exit_binding_id: Mapped[int | None] = mapped_column(BigInteger)
    reentry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reentry_delay_seconds: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    entry_order_id: Mapped[int | None] = mapped_column(BigInteger)
    binding_id: Mapped[int | None] = mapped_column(BigInteger)
    real_net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    real_fees: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rule_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{RULE_VERSION}'")
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_PENDING_OUTCOME}'")
    )
    variant_decisions_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    post_exit_returns_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UpbitProfitabilityMaDcEventEntity(Base):
    """MA Dead Cross Optimization Shadow Lab V1 — REAL MA_DEAD_CROSS anchor."""

    __tablename__ = "upbit_profitability_ma_dc_event"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "binding_id",
            name="uq_pislab_ma_dc_binding",
        ),
        Index(
            "ix_pislab_ma_dc_uba_at",
            "user_broker_account_id",
            "baseline_exit_at",
        ),
        {"schema": "operation"},
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    binding_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_order_id: Mapped[int | None] = mapped_column(BigInteger)
    entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    baseline_exit_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    baseline_exit_price: Mapped[Decimal] = mapped_column(
        Numeric(28, 12), nullable=False
    )
    baseline_net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    baseline_fees: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rule_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{RULE_VERSION}'")
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_ACTIVE}'")
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    variant_outcomes_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    path_state_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
