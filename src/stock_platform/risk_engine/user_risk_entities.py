"""STEP 8-2 — 시스템·사용자·계좌 리스크 설정 Entity."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
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


class SystemRiskSetting(Base):
    """플랫폼 시스템 기본 리스크 정책 (singleton_key=DEFAULT)."""

    __tablename__ = "system_risk_setting"
    __table_args__ = (
        UniqueConstraint(
            "singleton_key",
            name="uq_system_risk_setting_singleton",
        ),
        {"schema": "trading"},
    )

    system_risk_setting_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    singleton_key: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'DEFAULT'")
    )
    max_order_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    daily_max_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False
    )
    max_total_investment_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False
    )
    max_position_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False
    )
    max_position_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_position_weight: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False
    )
    max_investment_ratio: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, server_default=text("'0.70'")
    )
    allow_duplicate_buy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    daily_max_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False
    )
    daily_max_loss_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False
    )
    stop_loss_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    take_profit_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    trailing_stop_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    auto_trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    buy_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sell_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sell_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    account_paused: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # STEP 8-7
    max_order_quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8), nullable=False
    )
    daily_order_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    # ORDER_LIMIT_V2 — nullable (명시 저장 전 V1)
    daily_submit_limit: Mapped[int | None] = mapped_column(Integer)
    daily_filled_entry_limit: Mapped[int | None] = mapped_column(Integer)
    duplicate_order_window_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    # STEP 8-8
    max_open_orders: Mapped[int] = mapped_column(Integer, nullable=False)
    max_slippage_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False
    )
    anomaly_orders_per_minute: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    loop_detect_window_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    arm_ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[str | None] = mapped_column(String(100))
    updated_by: Mapped[str | None] = mapped_column(String(100))


class UserRiskSetting(Base):
    """사용자 기본 리스크 (NULL 필드는 시스템 상속)."""

    __tablename__ = "user_risk_setting"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_risk_setting_user"),
        {"schema": "trading"},
    )

    user_risk_setting_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="CASCADE",
            name="fk_user_risk_setting_user",
        ),
        nullable=False,
        index=True,
    )
    max_order_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    daily_max_order_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    max_total_investment_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2)
    )
    max_position_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    max_position_count: Mapped[int | None] = mapped_column(Integer)
    max_position_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    max_investment_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    allow_duplicate_buy: Mapped[bool | None] = mapped_column(Boolean)
    daily_max_loss_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    daily_max_loss_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    stop_loss_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    take_profit_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    trailing_stop_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    auto_trading_enabled: Mapped[bool | None] = mapped_column(Boolean)
    buy_enabled: Mapped[bool | None] = mapped_column(Boolean)
    sell_enabled: Mapped[bool | None] = mapped_column(Boolean)
    sell_only: Mapped[bool | None] = mapped_column(Boolean)
    account_paused: Mapped[bool | None] = mapped_column(Boolean)
    # STEP 8-7
    max_order_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    daily_order_limit: Mapped[int | None] = mapped_column(Integer)
    daily_submit_limit: Mapped[int | None] = mapped_column(Integer)
    daily_filled_entry_limit: Mapped[int | None] = mapped_column(Integer)
    duplicate_order_window_seconds: Mapped[int | None] = mapped_column(Integer)
    # STEP 8-8
    max_open_orders: Mapped[int | None] = mapped_column(Integer)
    max_slippage_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    anomaly_orders_per_minute: Mapped[int | None] = mapped_column(Integer)
    loop_detect_window_seconds: Mapped[int | None] = mapped_column(Integer)
    arm_ttl_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[str | None] = mapped_column(String(100))
    updated_by: Mapped[str | None] = mapped_column(String(100))


class UserBrokerAccountRiskSetting(Base):
    """UserBrokerAccount 계좌별 리스크 (NULL = 사용자/시스템 상속)."""

    __tablename__ = "user_broker_account_risk_setting"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            name="uq_uba_risk_setting_account",
        ),
        {"schema": "trading"},
    )

    user_broker_account_risk_setting_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="CASCADE",
            name="fk_uba_risk_setting_uba",
        ),
        nullable=False,
        index=True,
    )
    max_order_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    daily_max_order_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    max_total_investment_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2)
    )
    max_position_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    max_position_count: Mapped[int | None] = mapped_column(Integer)
    max_position_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    max_investment_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    allow_duplicate_buy: Mapped[bool | None] = mapped_column(Boolean)
    daily_max_loss_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    daily_max_loss_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    stop_loss_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    take_profit_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    trailing_stop_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    auto_trading_enabled: Mapped[bool | None] = mapped_column(Boolean)
    buy_enabled: Mapped[bool | None] = mapped_column(Boolean)
    sell_enabled: Mapped[bool | None] = mapped_column(Boolean)
    sell_only: Mapped[bool | None] = mapped_column(Boolean)
    account_paused: Mapped[bool | None] = mapped_column(Boolean)
    # STEP 8-7
    max_order_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    daily_order_limit: Mapped[int | None] = mapped_column(Integer)
    daily_submit_limit: Mapped[int | None] = mapped_column(Integer)
    daily_filled_entry_limit: Mapped[int | None] = mapped_column(Integer)
    duplicate_order_window_seconds: Mapped[int | None] = mapped_column(Integer)
    # STEP 8-8
    max_open_orders: Mapped[int | None] = mapped_column(Integer)
    max_slippage_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    anomaly_orders_per_minute: Mapped[int | None] = mapped_column(Integer)
    loop_detect_window_seconds: Mapped[int | None] = mapped_column(Integer)
    arm_ttl_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[str | None] = mapped_column(String(100))
    updated_by: Mapped[str | None] = mapped_column(String(100))
