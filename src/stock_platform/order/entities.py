from datetime import datetime
from decimal import Decimal
from typing import Any
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from stock_platform.database.base import Base

class TradingOrderEntity(Base):
    __tablename__ = "trading_order"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_trading_order_client_order_id"),
        Index("ix_trading_order_account_status", "account_id", "status_code"),
        Index("ix_trading_order_symbol_created", "exchange_code", "symbol", "created_at"),
        Index(
            "ix_trading_order_user_broker_account_id",
            "user_broker_account_id",
        ),
        Index(
            "ix_trading_order_uba_status",
            "user_broker_account_id",
            "status_code",
        ),
        # STEP 8-5-14 — Resolver Scheduler Due / Claim 조회
        Index(
            "ix_trading_order_resolver_due",
            "broker_code",
            "status_code",
            "next_remote_lookup_at",
        ),
        Index(
            "ix_trading_order_resolver_claim_expires",
            "resolver_claim_expires_at",
        ),
        Index(
            "ix_trading_order_uba_next_lookup",
            "user_broker_account_id",
            "next_remote_lookup_at",
        ),
        {"schema": "trading"},
    )

    order_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(50), nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(100))
    # STEP 2-5-2 — trading.paper_account.account_id 참조 (RESTRICT).
    # 기존 데이터에 미해소 orphan 1건(order_id=250)이 있어 DB 제약은
    # NOT VALID로 추가되며(향후 신규/변경 행부터 강제), ORM 메타데이터에는
    # 정상적으로 FK로 반영한다.
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id",
            ondelete="RESTRICT",
            name="fk_trading_order_account",
        ),
        nullable=False,
    )
    # STEP8-1 — 실계좌(UserBrokerAccount) 격리. Paper-only 주문은 NULL.
    user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="SET NULL",
            name="fk_trading_order_user_broker_account",
        ),
        nullable=True,
    )
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    strategy_code: Mapped[str | None] = mapped_column(String(100))
    strategy_deployment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment.strategy_deployment_id",
            ondelete="SET NULL",
            name="fk_trading_order_strategy_deployment",
        ),
        nullable=True,
    )
    # 계좌 성과 귀속 — 기존 strategy_code 와 별도 (공식 strategy_definition FK)
    strategy_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="SET NULL",
            name="fk_trading_order_strategy_id",
        ),
        nullable=True,
    )
    strategy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runtime_scope_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    account_strategy_link_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.account_strategy_link.account_strategy_link_id",
            ondelete="SET NULL",
            name="fk_trading_order_account_strategy_link",
        ),
        nullable=True,
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    execution_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
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
    original_order_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.trading_order.order_id",
            ondelete="SET NULL",
            name="fk_trading_order_original",
        ),
    )
    replaced_order_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.trading_order.order_id",
            ondelete="SET NULL",
            name="fk_trading_order_replaced",
        ),
    )
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # STEP 8-5-12 — Upbit client identifier / ambiguous tracking
    client_order_identifier: Mapped[str | None] = mapped_column(String(36))
    submission_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1"), default=1
    )
    first_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_submission_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    submission_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    ambiguous_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    ambiguity_reason: Mapped[str | None] = mapped_column(String(200))
    remote_lookup_status: Mapped[str | None] = mapped_column(String(40))
    remote_lookup_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    last_remote_lookup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    next_remote_lookup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    source_signal_id: Mapped[str | None] = mapped_column(String(100))
    source_signal_fingerprint: Mapped[str | None] = mapped_column(String(64))
    order_fingerprint: Mapped[str | None] = mapped_column(String(64))
    # STEP 8-5-14 — Ambiguous Resolver Scheduler DB Claim (원격 조회 전용)
    resolver_claimed_by: Mapped[str | None] = mapped_column(String(100))
    resolver_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    resolver_claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    resolver_run_token: Mapped[str | None] = mapped_column(String(64))
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
    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.trading_order.order_id",
            ondelete="CASCADE",
            name="fk_order_status_history_order",
        ),
        nullable=False,
    )
    previous_status_code: Mapped[str | None] = mapped_column(String(30))
    current_status_code: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, server_default=text("'SYSTEM'"))
    detail_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OrderSubmissionAttemptEntity(Base):
    """STEP 8-5-12 — 외부 주문 제출 Attempt (민감 Payload 미저장)."""

    __tablename__ = "order_submission_attempt"
    __table_args__ = (
        Index(
            "ix_order_submission_attempt_order",
            "order_id",
            "attempt_number",
        ),
        {"schema": "trading"},
    )

    attempt_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.trading_order.order_id",
            ondelete="CASCADE",
            name="fk_order_submission_attempt_order",
        ),
        nullable=False,
    )
    client_order_identifier: Mapped[str | None] = mapped_column(String(36))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    result_type: Mapped[str] = mapped_column(String(40), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    upbit_error_code: Mapped[str | None] = mapped_column(String(80))
    external_order_uuid: Mapped[str | None] = mapped_column(String(100))
    ambiguous: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )
    retry_action: Mapped[str | None] = mapped_column(String(40))
    correlation_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
