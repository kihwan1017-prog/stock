from datetime import datetime
from decimal import Decimal
from typing import Any
from sqlalchemy import BigInteger, DateTime, Identity, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from stock_platform.database.base import Base

class BrokerPendingOrderEntity(Base):
    __tablename__ = "broker_pending_order"
    __table_args__ = (
        UniqueConstraint("broker_code", "account_number", "broker_order_id",
                         name="uq_broker_pending_order_number"),
        {"schema": "trading"},
    )

    broker_pending_order_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    account_number: Mapped[str] = mapped_column(String(30), nullable=False)
    broker_order_id: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'KRX'"))
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, server_default=text("''"))
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    order_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False, server_default=text("0"))
    order_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False, server_default=text("0"))
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False, server_default=text("0"))
    average_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    status_code: Mapped[str] = mapped_column(String(30), nullable=False)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    synchronized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
