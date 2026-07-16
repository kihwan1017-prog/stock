from datetime import datetime
from decimal import Decimal
from typing import Any
from sqlalchemy import BigInteger, DateTime, Identity, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from stock_platform.database.base import Base

class TradingOrderEntity(Base):
    __tablename__ = "trading_order"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_trading_order_client_order_id"),
        Index("ix_trading_order_account_status", "account_id", "status_code"),
        Index("ix_trading_order_symbol_created", "exchange_code", "symbol", "created_at"),
        {"schema": "trading"},
    )

    order_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(50), nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(100))
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    strategy_code: Mapped[str | None] = mapped_column(String(100))
    strategy_deployment_id: Mapped[int | None] = mapped_column(BigInteger)
    portfolio_id: Mapped[int | None] = mapped_column(BigInteger)
    position_id: Mapped[int | None] = mapped_column(BigInteger)
    side_code: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type_code: Mapped[str] = mapped_column(String(20), nullable=False)
    time_in_force_code: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'DAY'"))
    order_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    order_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False, server_default=text("0"))
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False, server_default=text("0"))
    filled_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False, server_default=text("0"))
    average_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    status_code: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'CREATED'"))
    reject_code: Mapped[str | None] = mapped_column(String(100))
    reject_message: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_message: Mapped[str | None] = mapped_column(Text)
    original_order_id: Mapped[int | None] = mapped_column(BigInteger)
    replaced_order_id: Mapped[int | None] = mapped_column(BigInteger)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class TradingOrderStatusHistoryEntity(Base):
    __tablename__ = "trading_order_status_history"
    __table_args__ = (Index("ix_order_status_history_order", "order_id", "created_at"), {"schema": "trading"})
    order_status_history_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    previous_status_code: Mapped[str | None] = mapped_column(String(30))
    current_status_code: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, server_default=text("'SYSTEM'"))
    detail_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
