from __future__ import annotations

from datetime import datetime
from decimal import Decimal

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
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class RiskPolicyEntity(Base):
    """저장 가능한 위험관리 정책."""

    __tablename__ = "risk_policy"
    __table_args__ = (
        UniqueConstraint(
            "policy_name",
            name="uq_risk_policy_policy_name",
        ),
        {"schema": "strategy"},
    )

    policy_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    policy_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    position_sizing_mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    fixed_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2),
        nullable=True,
    )

    portfolio_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6),
        nullable=True,
    )

    risk_per_trade_ratio: Mapped[Decimal] = mapped_column(
        Numeric(10, 6),
        nullable=False,
        server_default=text("0.01"),
    )

    stop_loss_ratio: Mapped[Decimal] = mapped_column(
        Numeric(10, 6),
        nullable=False,
        server_default=text("0.03"),
    )

    take_profit_ratio: Mapped[Decimal] = mapped_column(
        Numeric(10, 6),
        nullable=False,
        server_default=text("0.06"),
    )

    trailing_stop_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6),
        nullable=True,
    )

    maximum_position_ratio: Mapped[Decimal] = mapped_column(
        Numeric(10, 6),
        nullable=False,
        server_default=text("0.20"),
    )

    maximum_positions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("5"),
    )

    minimum_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("10000"),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
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


class PositionPlanEntity(Base):
    """위험관리 엔진이 생성한 포지션 계획 이력."""

    __tablename__ = "position_plan"
    __table_args__ = (
        {"schema": "strategy"},
    )

    position_plan_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    policy_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    exchange_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    approved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    reason_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
    )

    order_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    entry_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    stop_loss_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    take_profit_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    trailing_stop_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6),
        nullable=True,
    )

    maximum_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
