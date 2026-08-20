"""UPBIT Full-Market Dynamic LIVE — ORM entities."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.operation.upbit_full_market.constants import (
    AI_GATE_ENFORCE,
    BINDING_STATUS_OPEN,
    MODE_FIXED_SYMBOL,
    SELECTION_STATUS_SELECTED,
    SOURCE_UPBIT_OPPORTUNITY_SCANNER,
    STATE_IDLE,
)


class UpbitFullMarketAssignmentEntity(Base):
    """UBA별 FIXED / FULL_MARKET 운영 assignment (deployment 심볼 mutate 금지)."""

    __tablename__ = "upbit_full_market_assignment"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            name="uq_upbit_fma_uba",
        ),
        {"schema": "operation"},
    )

    assignment_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    broker_code: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'UPBIT'")
    )
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    deployment_id: Mapped[int | None] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text(f"'{MODE_FIXED_SYMBOL}'"),
    )
    state: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text(f"'{STATE_IDLE}'"),
    )
    # deployment/template 원본 심볼 (FIXED fallback)
    template_symbol: Mapped[str | None] = mapped_column(String(40))
    current_symbol: Mapped[str | None] = mapped_column(String(40))
    active_selection_id: Mapped[int | None] = mapped_column(BigInteger)
    last_scanner_run_id: Mapped[str | None] = mapped_column(String(64))
    ai_live_gate_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text(f"'{AI_GATE_ENFORCE}'"),
    )
    warmup_ready: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    market_data_fresh: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    signals_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    selection_lease_token: Mapped[str | None] = mapped_column(String(64))
    selection_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    block_reason: Mapped[str | None] = mapped_column(String(200))
    last_error: Mapped[str | None] = mapped_column(Text)
    policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    enabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    enabled_by: Mapped[str | None] = mapped_column(String(100))
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    disabled_by: Mapped[str | None] = mapped_column(String(100))
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


class UpbitLiveCandidateSelectionEntity(Base):
    """Scanner → LIVE 선택 provenance (STEP12 lifecycle Candidate와 분리)."""

    __tablename__ = "upbit_live_candidate_selection"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "scanner_run_id",
            "symbol",
            name="uq_upbit_lcs_uba_run_symbol",
        ),
        {"schema": "operation"},
    )

    selection_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    deployment_id: Mapped[int | None] = mapped_column(BigInteger)
    scanner_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    market_data_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    liquidity: Mapped[float | None] = mapped_column(Float)
    technical_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    ai_analysis_id: Mapped[int | None] = mapped_column(BigInteger)
    ai_recommendation: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float)
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    selection_reason: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=text(f"'{SOURCE_UPBIT_OPPORTUNITY_SCANNER}'"),
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text(f"'{SELECTION_STATUS_SELECTED}'"),
    )
    skip_trace: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UpbitStrategyPositionBindingEntity(Base):
    """Dynamic strategy가 연 포지션만 자동 EXIT 대상."""

    __tablename__ = "upbit_strategy_position_binding"
    __table_args__ = {"schema": "operation"}

    binding_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    deployment_id: Mapped[int | None] = mapped_column(BigInteger)
    selection_id: Mapped[int | None] = mapped_column(BigInteger)
    slot_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text(f"'{BINDING_STATUS_OPEN}'"),
    )
    entry_order_id: Mapped[int | None] = mapped_column(BigInteger)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class UpbitPortfolioPolicyEntity(Base):
    """FULL_MARKET_PORTFOLIO 계좌 정책 (default OFF)."""

    __tablename__ = "upbit_portfolio_policy"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            name="uq_upbit_portfolio_policy_uba",
        ),
        {"schema": "operation"},
    )

    policy_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    max_positions: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    portfolio_capital_limit_krw: Mapped[float | None] = mapped_column(Float)
    per_position_target_pct: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0.08")
    )
    max_symbol_exposure_pct: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0.12")
    )
    max_total_exposure_pct: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0.30")
    )
    min_cash_reserve_pct: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0.60")
    )
    daily_loss_limit_pct: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0.02")
    )
    consecutive_loss_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    allow_averaging_down: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    allow_duplicate_symbol: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    entry_cooldown_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("300")
    )
    candidate_max_age_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1800")
    )
    portfolio_max_pending_entries: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    portfolio_daily_entry_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("10")
    )
    entry_state: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'RUNNING'"),
    )
    consecutive_loss_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
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


class UpbitPositionSlotEntity(Base):
    """Portfolio position slot — 한 slot = 한 active symbol."""

    __tablename__ = "upbit_position_slot"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "slot_no",
            name="uq_upbit_position_slot_uba_no",
        ),
        {"schema": "operation"},
    )

    slot_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    deployment_id: Mapped[int | None] = mapped_column(BigInteger)
    slot_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'EMPTY'"),
    )
    symbol: Mapped[str | None] = mapped_column(String(40))
    candidate_selection_id: Mapped[int | None] = mapped_column(BigInteger)
    scanner_run_id: Mapped[str | None] = mapped_column(String(64))
    ai_analysis_id: Mapped[int | None] = mapped_column(BigInteger)
    recommended_amount_krw: Mapped[float | None] = mapped_column(Float)
    allocated_amount_krw: Mapped[float | None] = mapped_column(Float)
    reserved_amount_krw: Mapped[float | None] = mapped_column(Float)
    clamp_reasons: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    entry_order_id: Mapped[int | None] = mapped_column(BigInteger)
    position_binding_id: Mapped[int | None] = mapped_column(BigInteger)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
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
