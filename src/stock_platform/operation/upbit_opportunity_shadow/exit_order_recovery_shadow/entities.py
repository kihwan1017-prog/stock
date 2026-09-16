"""ORM — Exit Order Recovery Shadow Lab (research only)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.constants import (
    RULE_VERSION,
    STATUS_ACTIVE,
)


class UpbitExitOrderRecoveryShadowObservationEntity(Base):
    """REAL AUTO_EXIT_SELL × shadow variant 관측 (forward-only)."""

    __tablename__ = "upbit_exit_order_recovery_shadow_observation"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "variant",
            "real_order_id",
            name="uq_eor_shadow_uba_var_order",
        ),
        Index(
            "ix_eor_shadow_uba_var_status",
            "user_broker_account_id",
            "variant",
            "status",
        ),
        Index("ix_eor_shadow_symbol", "symbol"),
        Index("ix_eor_shadow_enrolled", "enrolled_at"),
        Index("ix_eor_shadow_real_order", "real_order_id"),
        {"schema": "operation"},
    )

    observation_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variant: Mapped[str] = mapped_column(String(8), nullable=False)
    cohort: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    binding_id: Mapped[int | None] = mapped_column(BigInteger)
    real_order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    broker_uuid: Mapped[str | None] = mapped_column(String(80))
    exit_reason: Mapped[str | None] = mapped_column(String(64))
    real_order_type: Mapped[str | None] = mapped_column(String(20))
    real_limit_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    real_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_ACTIVE}'")
    )
    shadow_trigger_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    shadow_trigger_age_seconds: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    market_price_at_trigger: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    best_bid_at_trigger: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    best_ask_at_trigger: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    remaining_qty_at_trigger: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    shadow_action: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'NO_ACTION'")
    )
    shadow_reference_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    real_terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    real_terminal_state: Mapped[str | None] = mapped_column(String(40))
    real_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    real_filled_qty: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    real_time_to_fill_seconds: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    shadow_fill_status: Mapped[str | None] = mapped_column(String(40))
    shadow_estimated_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    shadow_time_to_fill_seconds: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    shadow_slippage_bps: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    shadow_incremental_pnl: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    shadow_incremental_cost: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    evidence_quality: Mapped[str | None] = mapped_column(String(16))
    mae_while_waiting: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    mfe_while_waiting: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    max_adverse_move_while_waiting: Mapped[Decimal | None] = mapped_column(
        Numeric(28, 8)
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    rule_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{RULE_VERSION}'")
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default=text("'{}'")
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
