"""Symbol AUTO 제외 / Symbol hold (additive)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class SymbolAutoExclusionEntity(Base):
    """사용자가 자동매매에서 명시 제외한 Symbol (보유와 무관)."""

    __tablename__ = "symbol_auto_exclusion"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "broker_code",
            "symbol",
            name="uq_symbol_auto_exclusion_uba_broker_symbol",
        ),
        {"schema": "operation"},
    )

    symbol_auto_exclusion_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    reason: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[str | None] = mapped_column(String(80))
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
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


class SymbolOwnershipHoldEntity(Base):
    """동일 Symbol MANUAL/AUTO 충돌 시 Symbol 단위 fail-closed."""

    __tablename__ = "symbol_ownership_hold"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "broker_code",
            "symbol",
            name="uq_symbol_ownership_hold_uba_broker_symbol",
        ),
        {"schema": "operation"},
    )

    symbol_ownership_hold_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'ACTIVE'")
    )
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    detail_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    cleared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
