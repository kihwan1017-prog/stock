"""ORM — upbit churn guard shadow episode (observability only)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.constants import (
    CHURN_GUARD_VERSION,
    FAMILY,
    MODE,
    STATUS_ACTIVE,
)


class UpbitChurnGuardShadowEpisodeEntity(Base):
    """동일 UBA+symbol churn episode — REAL block 없음."""

    __tablename__ = "upbit_churn_guard_shadow_episode"
    __table_args__ = {"schema": "operation"}

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'UPBIT'")
    )
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    family: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{FAMILY}'")
    )
    rule_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=text(f"'{CHURN_GUARD_VERSION}'"),
    )
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text(f"'{MODE}'")
    )
    real_block_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text(f"'{STATUS_ACTIVE}'")
    )
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    primary_classification: Mapped[str] = mapped_column(String(64), nullable=False)
    secondary_classifications_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    round_trip_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    loss_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    consecutive_loss_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    fees: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    reentry_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    min_reentry_seconds: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    dominant_exit_reason: Mapped[str | None] = mapped_column(String(64))
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_alert_severity: Mapped[str | None] = mapped_column(String(20))
    telegram_dedupe_key: Mapped[str | None] = mapped_column(String(160))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    detail_json: Mapped[dict[str, Any]] = mapped_column(
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
