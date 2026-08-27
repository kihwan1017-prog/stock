"""ORM — Upbit MA exit forward shadow (research only)."""

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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.constants import (
    PRIMARY_SHADOW_RULE,
    RULE_VERSION,
    STATUS_ACTIVE,
)


class UpbitMaExitForwardShadowEntity(Base):
    """Baseline(REAL) vs Confirm2 shadow — 포지션당 1 row, binding_id unique."""

    __tablename__ = "upbit_ma_exit_forward_shadow"
    __table_args__ = {"schema": "operation"}

    shadow_row_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    market: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'UPBIT'")
    )
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    binding_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    entry_order_id: Mapped[int | None] = mapped_column(BigInteger)
    entry_fill_id: Mapped[int | None] = mapped_column(BigInteger)
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
    baseline_exit_reason: Mapped[str | None] = mapped_column(String(64))
    baseline_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    baseline_exit_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    baseline_gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    baseline_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    baseline_net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    shadow_rule: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=text(f"'{PRIMARY_SHADOW_RULE}'"),
    )
    shadow_first_dead_cross_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    shadow_confirmation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    shadow_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shadow_exit_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    shadow_exit_reason: Mapped[str | None] = mapped_column(String(64))
    shadow_gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    shadow_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    shadow_net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    difference_net: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    secondary_shadow_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    shadow_state_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    context_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Data Trust — INVALID 구간 표본 quarantine (삭제 금지)
    data_quality_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'UNKNOWN'")
    )
    included_in_research_metrics: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    quarantine_reason: Mapped[str | None] = mapped_column(String(80))
    quality_window_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
