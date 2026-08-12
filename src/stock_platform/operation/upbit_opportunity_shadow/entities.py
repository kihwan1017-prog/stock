"""UPBIT Opportunity Scanner Paper Shadow ORM."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
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
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_ACTIVE,
)


class UpbitOpportunityShadowEntity(Base):
    """Scanner ALLOW/REDUCE 가상 진입 — 실주문 FK 없음."""

    __tablename__ = "upbit_opportunity_shadow"
    __table_args__ = {"schema": "trading"}

    shadow_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    scanner_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    recommendation: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=SHADOW_STATUS_ACTIVE,
    )
    scanner_rank: Mapped[int | None] = mapped_column(Integer)
    scanner_score: Mapped[float | None] = mapped_column(Float)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(28, 12), nullable=False)
    assumed_amount_krw: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    trend: Mapped[str | None] = mapped_column(String(40))
    momentum: Mapped[str | None] = mapped_column(String(40))
    volatility: Mapped[str | None] = mapped_column(String(40))
    ma5: Mapped[float | None] = mapped_column(Float)
    ma20: Mapped[float | None] = mapped_column(Float)
    rsi14: Mapped[float | None] = mapped_column(Float)
    macd: Mapped[float | None] = mapped_column(Float)
    atr14: Mapped[float | None] = mapped_column(Float)
    volume_surge: Mapped[float | None] = mapped_column(Float)
    trade_value_24h: Mapped[float | None] = mapped_column(Float)
    market_analysis_id: Mapped[int | None] = mapped_column(BigInteger)
    live_auto_start: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    price_5m: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    return_5m_pct: Mapped[float | None] = mapped_column(Float)
    evaluated_5m_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    price_15m: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    return_15m_pct: Mapped[float | None] = mapped_column(Float)
    evaluated_15m_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    price_30m: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    return_30m_pct: Mapped[float | None] = mapped_column(Float)
    evaluated_30m_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    price_60m: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    return_60m_pct: Mapped[float | None] = mapped_column(Float)
    evaluated_60m_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    mfe_pct: Mapped[float | None] = mapped_column(Float)
    mae_pct: Mapped[float | None] = mapped_column(Float)
    sl_hit: Mapped[bool | None] = mapped_column(Boolean)
    tp_hit: Mapped[bool | None] = mapped_column(Boolean)
    sl_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tp_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    evaluation_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
