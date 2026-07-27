from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class PositionLimitEntity(Base):
    """STEP 8-5-19 — UBA/Paper 기준 Position Limit."""

    __tablename__ = "position_limit"
    __table_args__ = (
        CheckConstraint(
            "("
            "(user_broker_account_id IS NOT NULL AND paper_account_id IS NULL "
            "AND account_scope_type = 'LIVE') OR "
            "(user_broker_account_id IS NULL AND paper_account_id IS NOT NULL "
            "AND account_scope_type = 'PAPER') OR "
            "(user_broker_account_id IS NULL AND paper_account_id IS NULL "
            "AND account_scope_type = 'LEGACY_ORPHAN')"
            ")",
            name="ck_position_limit_exactly_one_scope",
        ),
        Index(
            "uq_position_limit_uba_symbol",
            "user_broker_account_id",
            "exchange_code",
            "symbol",
            unique=True,
            postgresql_where=text("user_broker_account_id IS NOT NULL"),
        ),
        Index(
            "uq_position_limit_paper_symbol",
            "paper_account_id",
            "exchange_code",
            "symbol",
            unique=True,
            postgresql_where=text("paper_account_id IS NOT NULL"),
        ),
        {"schema": "operation"},
    )

    position_limit_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    broker_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'KIWOOM'"),
    )
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    paper_account_id: Mapped[int | None] = mapped_column(BigInteger)
    account_scope_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'UNKNOWN'"),
    )
    masked_account_ref: Mapped[str | None] = mapped_column(String(40))
    exchange_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    max_quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
    )
    max_position_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )
    max_position_weight: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
