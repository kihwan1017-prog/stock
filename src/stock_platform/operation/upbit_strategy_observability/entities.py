# -*- coding: utf-8 -*-
"""ORM entities — Upbit strategy observability V1 (analytics schema)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Index,
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


class UpbitStrategyObsScannerUniverseEntity(Base):
    """One row per symbol per scanner run — SELECTED and NOT_SELECTED."""

    __tablename__ = "upbit_strategy_obs_scanner_universe"
    __table_args__ = (
        UniqueConstraint(
            "scanner_run_id",
            "symbol",
            name="uq_upbit_obs_scanner_run_symbol",
        ),
        Index(
            "ix_upbit_obs_scanner_run_selected",
            "scanner_run_id",
            "selected",
        ),
        Index(
            "ix_upbit_obs_scanner_created",
            "created_at",
        ),
        {"schema": "operation"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    scanner_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_rank: Mapped[int | None] = mapped_column(BigInteger)
    candidate_score: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    rejected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    reject_reason: Mapped[str | None] = mapped_column(String(120))
    scanner_source: Mapped[str | None] = mapped_column(String(40))
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    rule_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'UPBIT_STRATEGY_OBS_V1'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UpbitStrategyObsEventEntity(Base):
    """Signal / admission / exit / regime snapshots — observation only."""

    __tablename__ = "upbit_strategy_obs_event"
    __table_args__ = (
        Index(
            "ix_upbit_obs_event_uba_type_created",
            "user_broker_account_id",
            "event_type",
            "created_at",
        ),
        Index("ix_upbit_obs_event_symbol_created", "symbol", "created_at"),
        Index("ix_upbit_obs_event_signal_id", "signal_id"),
        {"schema": "operation"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str | None] = mapped_column(String(40))
    scanner_run_id: Mapped[str | None] = mapped_column(String(64))
    selection_id: Mapped[int | None] = mapped_column(BigInteger)
    signal_id: Mapped[str | None] = mapped_column(String(120))
    order_id: Mapped[int | None] = mapped_column(BigInteger)
    binding_id: Mapped[int | None] = mapped_column(BigInteger)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    rule_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'UPBIT_STRATEGY_OBS_V1'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UpbitStrategyObsOrderTimelineEntity(Base):
    """BUY/SELL timeline stamps for latency analysis."""

    __tablename__ = "upbit_strategy_obs_order_timeline"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "side_code",
            name="uq_upbit_obs_order_timeline_order_side",
        ),
        Index(
            "ix_upbit_obs_timeline_uba_created",
            "user_broker_account_id",
            "created_at",
        ),
        {"schema": "operation"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    side_code: Mapped[str] = mapped_column(String(8), nullable=False)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    binding_id: Mapped[int | None] = mapped_column(BigInteger)
    signal_id: Mapped[str | None] = mapped_column(String(120))
    selection_id: Mapped[int | None] = mapped_column(BigInteger)
    candidate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admission_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intent_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    broker_submit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    broker_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fill_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    note_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    rule_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'UPBIT_STRATEGY_OBS_V1'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UpbitStrategyObsPostTradeEntity(Base):
    """Post-close MFE/MAE / post-exit / counterfactual — ANALYTICS ONLY.

    Must never be read by entry admission, MA evaluator, or order submit paths.
    """

    __tablename__ = "upbit_strategy_obs_post_trade"
    __table_args__ = (
        UniqueConstraint(
            "binding_id",
            name="uq_upbit_obs_post_trade_binding",
        ),
        Index(
            "ix_upbit_obs_post_trade_uba_closed",
            "user_broker_account_id",
            "closed_at",
        ),
        {"schema": "operation"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    binding_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    mfe_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    mae_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    time_to_mfe_seconds: Mapped[int | None] = mapped_column(BigInteger)
    time_to_mae_seconds: Mapped[int | None] = mapped_column(BigInteger)
    post_exit_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    analytics_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Explicit marker — trading code must not consume this table
    lookahead_forbidden_for_trading: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    rule_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'UPBIT_STRATEGY_OBS_V1'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text)
