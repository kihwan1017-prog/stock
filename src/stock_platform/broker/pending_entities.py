from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class BrokerPendingOrderEntity(Base):
    """브로커 미체결 — 내부 식별은 user_broker_account_id."""

    __tablename__ = "broker_pending_order"
    __table_args__ = (
        Index(
            "uq_broker_pending_order_uba_order",
            "broker_code",
            "user_broker_account_id",
            "broker_order_id",
            unique=True,
            postgresql_where=text("user_broker_account_id IS NOT NULL"),
        ),
        Index("ix_broker_pending_order_uba", "user_broker_account_id"),
        {"schema": "trading"},
    )

    broker_pending_order_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    # Broker 경계 토큰 — 내부 FK 대체 금지 (UBA:{id} 또는 마스킹)
    account_number: Mapped[str] = mapped_column(String(30), nullable=False)
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="RESTRICT",
            name="fk_broker_pending_order_uba",
        ),
        nullable=False,
    )
    masked_account_ref: Mapped[str | None] = mapped_column(String(40))
    broker_order_id: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange_code: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'KRX'")
    )
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(
        String(200), nullable=False, server_default=text("''")
    )
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    order_quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8), nullable=False, server_default=text("0")
    )
    order_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    filled_quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8), nullable=False, server_default=text("0")
    )
    remaining_quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8), nullable=False, server_default=text("0")
    )
    average_fill_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    status_code: Mapped[str] = mapped_column(String(30), nullable=False)
    ordered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    synchronized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
