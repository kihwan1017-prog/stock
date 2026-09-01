"""ORM — Exit Optimization Shadow Lab V3 (research only)."""

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
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.constants import (
    RULE_VERSION,
    STATUS_ACTIVE,
)


class UpbitExitOptimizationShadowV3PolicyEntity(Base):
    """Versioned V3 policy parameters — GPT/ops tuning without code deploy."""

    __tablename__ = "upbit_exit_optimization_shadow_v3_policy"
    __table_args__ = {"schema": "operation"}

    policy_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UpbitExitOptimizationShadowV3EnrollmentEntity(Base):
    """Binding당 1 enrollment — REAL baseline + shared price-path state."""

    __tablename__ = "upbit_exit_optimization_shadow_v3_enrollment"
    __table_args__ = (
        UniqueConstraint("binding_id", name="uq_eosv3_enrollment_binding"),
        Index("ix_eosv3_enrollment_uba", "user_broker_account_id"),
        Index("ix_eosv3_enrollment_status", "status"),
        {"schema": "operation"},
    )

    enrollment_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    market: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'UPBIT'")
    )
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
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_ACTIVE}'")
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # REAL baseline (R0 SoT)
    real_exit_reason: Mapped[str | None] = mapped_column(String(64))
    real_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    real_exit_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    real_gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    real_fees: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    real_net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    real_holding_seconds: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    # shared path observation
    path_state_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    data_quality_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'UNKNOWN'")
    )
    included_in_research_metrics: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    real_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class UpbitExitOptimizationShadowV3VariantEntity(Base):
    """Variant별 shadow observation — REAL과 분리."""

    __tablename__ = "upbit_exit_optimization_shadow_v3_variant"
    __table_args__ = (
        UniqueConstraint(
            "binding_id",
            "variant_id",
            name="uq_eosv3_variant_binding",
        ),
        Index("ix_eosv3_variant_enrollment", "enrollment_id"),
        Index("ix_eosv3_variant_status", "variant_id", "status"),
        {"schema": "operation"},
    )

    variant_row_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    enrollment_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    binding_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variant_id: Mapped[str] = mapped_column(String(8), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_ACTIVE}'")
    )
    # shadow outcome
    shadow_exit_reason: Mapped[str | None] = mapped_column(String(64))
    shadow_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shadow_exit_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    shadow_gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    shadow_estimated_exit_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    shadow_estimated_net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    holding_seconds: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    mfe_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    mae_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    peak_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    current_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    short_ma: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    long_ma: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    ma_relation: Mapped[str | None] = mapped_column(String(32))
    estimated_entry_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    estimated_round_trip_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    trigger_reason: Mapped[str | None] = mapped_column(String(64))
    defer_reason: Mapped[str | None] = mapped_column(String(128))
    deferred_trailing_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    baseline_terminal_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    shadow_terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    continuation_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
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
