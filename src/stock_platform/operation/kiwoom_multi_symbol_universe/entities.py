"""ORM — KIWOOM multi-symbol monitor roster + durable cross state."""

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
from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    MARKET,
    RULE_VERSION,
)


class KiwoomMultiSymbolMonitorEntity(Base):
    """현재 TOP-N 감시 roster 스냅샷 (장중 refresh)."""

    __tablename__ = "kiwoom_multi_symbol_monitor"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "refresh_batch_id",
            "symbol",
            name="uq_kiwoom_ms_monitor_uba_batch_symbol",
        ),
        {"schema": "operation"},
    )

    monitor_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    market: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text(f"'{MARKET}'")
    )
    refresh_batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    trading_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    selection_reason: Mapped[str | None] = mapped_column(String(120))
    sma5: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    sma20: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    cross_state: Mapped[str | None] = mapped_column(String(40))
    block_reason: Mapped[str | None] = mapped_column(String(64))
    signal_status: Mapped[str | None] = mapped_column(String(32))
    rule_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{RULE_VERSION}'")
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class KiwoomMultiSymbolCrossStateEntity(Base):
    """symbol별 MA/cross state — monitor roster와 분리 (refresh stability)."""

    __tablename__ = "kiwoom_multi_symbol_cross_state"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "symbol",
            name="uq_kiwoom_ms_cross_uba_symbol",
        ),
        {"schema": "operation"},
    )

    cross_state_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    sma5: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    sma20: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    prev_sma5: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    prev_sma20: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    cross_state: Mapped[str] = mapped_column(String(40), nullable=False)
    last_cross_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    insufficient_history: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_signal_fingerprint: Mapped[str | None] = mapped_column(String(96))
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
