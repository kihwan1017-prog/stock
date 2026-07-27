"""STEP 8-5-16 — Account Daily Settlement ORM."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AccountDailySettlementEntity(Base):
    """계좌·일자 단위 EOD/Daily 정산 결과."""

    __tablename__ = "account_daily_settlement"
    __table_args__ = (
        CheckConstraint(
            "(user_broker_account_id IS NOT NULL AND paper_account_id IS NULL)"
            " OR (user_broker_account_id IS NULL AND paper_account_id IS NOT NULL)",
            name="ck_account_daily_settlement_account_xor",
        ),
        CheckConstraint(
            "retry_count >= 0",
            name="ck_account_daily_settlement_retry_nonneg",
        ),
        CheckConstraint(
            "open_order_count >= 0 AND unresolved_order_count >= 0"
            " AND position_mismatch_count >= 0",
            name="ck_account_daily_settlement_counts_nonneg",
        ),
        Index(
            "ix_account_daily_settlement_date_status",
            "market_date",
            "status_code",
        ),
        Index(
            "ix_account_daily_settlement_broker_date",
            "broker_code",
            "market_date",
        ),
        {"schema": "trading"},
    )

    settlement_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    paper_account_id: Mapped[int | None] = mapped_column(BigInteger)
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    market_date: Mapped[date] = mapped_column(Date, nullable=False)
    calendar_revision: Mapped[int | None] = mapped_column(Integer)
    settlement_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    external_sync_status: Mapped[str | None] = mapped_column(String(40))
    order_reconciliation_status: Mapped[str | None] = mapped_column(String(40))
    execution_reconciliation_status: Mapped[str | None] = mapped_column(
        String(40)
    )
    position_reconciliation_status: Mapped[str | None] = mapped_column(
        String(40)
    )
    cash_reconciliation_status: Mapped[str | None] = mapped_column(String(40))
    pnl_calculation_status: Mapped[str | None] = mapped_column(String(40))
    open_order_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    unresolved_order_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    position_mismatch_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    cash_mismatch_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
        default=Decimal("0"),
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default=text("0")
    )
    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default=text("0")
    )
    gross_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default=text("0")
    )
    fees: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default=text("0")
    )
    taxes: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default=text("0")
    )
    net_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default=text("0")
    )
    opening_equity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    closing_equity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    external_equity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    internal_equity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    equity_difference: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    result_code: Mapped[str | None] = mapped_column(String(80))
    result_summary: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    external_snapshot_meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    detail_payload: Mapped[dict[str, Any]] = mapped_column(
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


class AccountDailySettlementIssueEntity(Base):
    """정산 불일치·경고 상세."""

    __tablename__ = "account_daily_settlement_issue"
    __table_args__ = (
        Index(
            "ix_account_daily_settlement_issue_settlement",
            "settlement_id",
            "issue_type",
        ),
        Index(
            "ix_account_daily_settlement_issue_unresolved",
            "resolved",
            "severity",
        ),
        {"schema": "trading"},
    )

    issue_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    settlement_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.account_daily_settlement.settlement_id",
            ondelete="CASCADE",
            name="fk_settlement_issue_settlement",
        ),
        nullable=False,
    )
    issue_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'CRITICAL'"),
    )
    symbol: Mapped[str | None] = mapped_column(String(40))
    local_value: Mapped[str | None] = mapped_column(Text)
    external_value: Mapped[str | None] = mapped_column(Text)
    difference: Mapped[str | None] = mapped_column(Text)
    tolerance: Mapped[str | None] = mapped_column(Text)
    result_code: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    resolved_by: Mapped[str | None] = mapped_column(String(150))
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class LedgerAdjustmentEntity(Base):
    """수동 Ledger 조정 요청 (자동 적용 UI 없음)."""

    __tablename__ = "ledger_adjustment"
    __table_args__ = (
        CheckConstraint(
            "(user_broker_account_id IS NOT NULL AND paper_account_id IS NULL)"
            " OR (user_broker_account_id IS NULL AND paper_account_id IS NOT NULL)",
            name="ck_ledger_adjustment_account_xor",
        ),
        Index("ix_ledger_adjustment_status", "status_code"),
        {"schema": "trading"},
    )

    ledger_adjustment_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    paper_account_id: Mapped[int | None] = mapped_column(BigInteger)
    market_date: Mapped[date | None] = mapped_column(Date)
    asset_code: Mapped[str] = mapped_column(String(40), nullable=False)
    adjustment_type: Mapped[str] = mapped_column(String(40), nullable=False)
    before_value: Mapped[str | None] = mapped_column(Text)
    adjustment_value: Mapped[str | None] = mapped_column(Text)
    after_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(150), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(150))
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'REQUESTED'"),
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
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
