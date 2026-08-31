"""ORM — post-exit re-entry cooldown shadow (research only)."""

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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.operation.upbit_opportunity_shadow.reentry_cooldown_shadow.constants import (
    FAMILY,
    RULE_VERSION,
    STATUS_OBSERVED,
)


class UpbitPostExitReentryCooldownShadowEntity(Base):
    """동일 symbol 재진입 관찰 — REAL entry block 없음."""

    __tablename__ = "upbit_post_exit_reentry_cooldown_shadow"
    __table_args__ = {"schema": "operation"}

    shadow_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'UPBIT'")
    )
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    family: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{FAMILY}'")
    )
    rule_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{RULE_VERSION}'")
    )
    previous_exit_order_id: Mapped[int | None] = mapped_column(BigInteger)
    previous_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_exit_reason: Mapped[str | None] = mapped_column(String(64))
    new_entry_order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_entry_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    gap_seconds: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_OBSERVED}'")
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # R0/R1/R2/R3 would_block + impact JSON
    variants_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    baseline_reentry_net: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    context_json: Mapped[dict[str, Any]] = mapped_column(
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
