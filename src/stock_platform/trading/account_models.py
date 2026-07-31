from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class PaperAccount(Base):
    """모의투자 계좌."""

    __tablename__ = "paper_account"
    __table_args__ = (
        UniqueConstraint(
            "account_name",
            name="uq_paper_account_account_name",
        ),
        {"schema": "trading"},
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    # STEP52 — 로그인 회원 소유권 (nullable: 레거시 행 호환)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="SET NULL",
            name="fk_paper_account_user",
        ),
        nullable=True,
        index=True,
    )

    account_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    currency_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=text("'KRW'"),
    )

    initial_cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    available_cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    realized_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )

    # STEP65 — 기본/활성 계좌
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )

    # 통합 브로커 메타 (nullable — 레거시 호환)
    broker_code: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    exchange_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
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

    # Soft delete — Hard Delete 금지(주문/체결 이력 보존)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class UserBrokerAccount(Base):
    """회원별 Broker 계좌 연결 (평문 계좌번호·시크릿 미저장)."""

    __tablename__ = "user_broker_account"
    __table_args__ = (
        # STEP 2-5-1 — Soft Delete 전환: 삭제되지 않은 행에만 유니크성 강제
        # (uq_user_broker_account_ref 전체 UniqueConstraint 대체, 삭제 후 재연결 허용)
        Index(
            "ux_user_broker_account_ref_active",
            "user_id",
            "broker_code",
            "account_ref_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": "trading"},
    )

    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="CASCADE",
            name="fk_user_broker_account_user",
        ),
        nullable=False,
        index=True,
    )

    broker_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    account_alias: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # SHA-256 hex — 원문 계좌번호는 저장하지 않음
    account_ref_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    masked_account_number: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    currency_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=text("'KRW'"),
    )

    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )

    # STEP 8-7 — 계좌별 LIVE 실주문 승인 (기본 OFF)
    live_order_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    live_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    live_approved_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # STEP 8-8 — LIVE ARM (5분 토큰)
    live_armed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    arm_token_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    arm_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    arm_armed_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    arm_armed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    connection_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'DISCONNECTED'"),
    )

    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    # STEP 2-5-1 — Soft delete (PaperAccount와 동일 패턴). Hard Delete 금지.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class PaperPosition(Base):
    """모의 계좌의 종목별 보유 포지션."""

    __tablename__ = "paper_position"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "exchange_code",
            "symbol",
            name="uq_paper_position_account_symbol",
        ),
        {"schema": "trading"},
    )

    position_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id",
            ondelete="CASCADE",
            name="fk_paper_position_account",
        ),
        nullable=False,
    )

    exchange_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
        server_default=text("0"),
    )

    average_entry_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )

    highest_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )

    realized_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
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


class PaperTrade(Base):
    """모의 체결로 생성된 매매 원장."""

    __tablename__ = "paper_trade"
    __table_args__ = (
        {"schema": "trading"},
    )

    trade_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id",
            ondelete="CASCADE",
            name="fk_paper_trade_account",
        ),
        nullable=False,
    )

    order_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_order.order_id",
            ondelete="SET NULL",
            name="fk_paper_trade_order",
        ),
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

    side: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 8),
        nullable=False,
    )

    fill_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    trade_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    realized_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        server_default=text("0"),
    )

    traded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
