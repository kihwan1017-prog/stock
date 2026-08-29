"""ORM — Upbit exit strategy forward shadow (research only)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
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
from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.constants import (
    RULE_VERSION,
    SAMPLE_NATURAL_AUTO,
    STATUS_ACTIVE,
)


class UpbitExitStrategyShadowEntity(Base):
    """Natural AUTO entry × exit-family variant — observation only."""

    __tablename__ = "upbit_exit_strategy_shadow"
    __table_args__ = (
        UniqueConstraint(
            "entry_order_id",
            "strategy_family",
            "variant_code",
            name="uq_exit_strat_shadow_entry_family_variant",
        ),
        {"schema": "operation"},
    )

    shadow_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    deployment_id: Mapped[int | None] = mapped_column(BigInteger)
    binding_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    entry_order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    broker_order_uuid: Mapped[str | None] = mapped_column(String(80))
    entry_fill_id: Mapped[str | None] = mapped_column(String(80))
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    entry_qty: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    entry_notional: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    entry_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    strategy_family: Mapped[str] = mapped_column(String(32), nullable=False)
    variant_code: Mapped[str] = mapped_column(String(40), nullable=False)
    threshold_value: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    time_horizon_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_ACTIVE}'")
    )
    trigger_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    peak_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    peak_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfe_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    mae_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    buy_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    slippage: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    hold_seconds: Mapped[int | None] = mapped_column(Integer)
    actual_exit_order_id: Mapped[int | None] = mapped_column(BigInteger)
    actual_exit_reason: Mapped[str | None] = mapped_column(String(64))
    actual_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_exit_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    actual_net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sample_class: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text(f"'{SAMPLE_NATURAL_AUTO}'"),
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    state_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    rule_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{RULE_VERSION}'")
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
