"""외부(브로커) 주문·체결 이력 — trading_order와 분리 보존."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class BrokerExternalOrderHistoryEntity(Base):
    """원격 주문 이력 스냅샷 — 자동매매 trading_order와 분리."""

    __tablename__ = "broker_external_order_history"
    __table_args__ = (
        UniqueConstraint(
            "broker_code",
            "external_order_id",
            name="uq_broker_ext_order_broker_uuid",
        ),
        {"schema": "operation"},
    )

    broker_external_order_history_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    external_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    external_order_id_masked: Mapped[str | None] = mapped_column(String(40))
    market_code: Mapped[str | None] = mapped_column(String(40))
    side_code: Mapped[str | None] = mapped_column(String(10))
    order_type_code: Mapped[str | None] = mapped_column(String(30))
    order_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    requested_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    executed_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    remaining_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    paid_fee: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    locked_amount: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    external_status: Mapped[str | None] = mapped_column(String(40))
    external_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    external_done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    raw_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    import_policy: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        server_default=text("'PRESERVE_REMOTE_HISTORY'"),
    )
    source_conflict_id: Mapped[int | None] = mapped_column(BigInteger)
    imported_by: Mapped[str | None] = mapped_column(String(100))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
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
    )


class BrokerExternalTradeHistoryEntity(Base):
    """원격 체결 이력 — trading_order_execution과 분리."""

    __tablename__ = "broker_external_trade_history"
    __table_args__ = (
        UniqueConstraint(
            "broker_code",
            "external_trade_id",
            name="uq_broker_ext_trade_broker_uuid",
        ),
        {"schema": "operation"},
    )

    broker_external_trade_history_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    external_trade_id: Mapped[str] = mapped_column(String(100), nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    market_code: Mapped[str | None] = mapped_column(String(40))
    side_code: Mapped[str | None] = mapped_column(String(10))
    trade_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    trade_volume: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    funds: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    fee: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    raw_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_conflict_id: Mapped[int | None] = mapped_column(BigInteger)
    imported_by: Mapped[str | None] = mapped_column(String(100))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
