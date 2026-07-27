from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class BrokerAccountSnapshotEntity(Base):
    """브로커 계좌 조회 결과 — UserBrokerAccount에 바인딩된 스냅샷."""

    __tablename__ = "broker_account_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "broker_code",
            "account_number",
            name="uq_broker_account_snapshot_account",
        ),
        CheckConstraint(
            "snapshot_status IN ("
            "'ACTIVE','ORPHAN','STALE','SUPERSEDED','INVALID',"
            "'REBIND_PENDING','REBOUND','RETIRED','PURGED')",
            name="ck_broker_account_snapshot_status",
        ),
        CheckConstraint(
            "snapshot_generation >= 1 AND snapshot_version >= 1",
            name="ck_broker_account_snapshot_generation_pos",
        ),
        Index(
            "ix_broker_account_snapshot_uba",
            "user_broker_account_id",
        ),
        Index(
            "ix_broker_account_snapshot_status_time",
            "snapshot_status",
            "snapshot_time",
        ),
        {"schema": "trading"},
    )

    broker_account_snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    broker_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    account_number: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    # STEP 8-5-17 — 명시적 UBA Binding (휴리스틱 금지)
    user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="SET NULL",
            name="fk_broker_account_snapshot_uba",
        ),
        nullable=True,
    )
    paper_account_id: Mapped[int | None] = mapped_column(BigInteger)
    snapshot_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )
    snapshot_generation: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("1"),
        default=1,
    )
    snapshot_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
        default=1,
    )
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    snapshot_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    broker_server_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    currency_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=text("'KRW'"),
    )
    deposit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    available_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    total_purchase_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    total_evaluation_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    total_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    total_return_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        server_default=text("0"),
    )
    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    synchronized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class BrokerPositionSnapshotEntity(Base):
    """브로커 계좌 보유종목 스냅샷 — UBA Binding."""

    __tablename__ = "broker_position_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "broker_code",
            "account_number",
            "exchange_code",
            "symbol",
            name="uq_broker_position_snapshot_symbol",
        ),
        Index(
            "ix_broker_position_snapshot_uba",
            "user_broker_account_id",
        ),
        {"schema": "trading"},
    )

    broker_position_snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    broker_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    account_number: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    snapshot_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )
    exchange_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'KRX'"),
    )
    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
        server_default=text("0"),
    )
    available_quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
        server_default=text("0"),
    )
    average_purchase_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )
    current_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )
    purchase_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    evaluation_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )
    return_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        server_default=text("0"),
    )
    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    synchronized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
