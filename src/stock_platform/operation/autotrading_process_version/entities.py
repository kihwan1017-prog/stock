"""ORM — AutoTrading process version / logic / change / execution trace."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.operation.autotrading_process_version.constants import (
    STATUS_ACTIVE,
    TRACE_UNKNOWN,
)


class AutoTradingProcessVersionEntity(Base):
    __tablename__ = "autotrading_process_version"
    __table_args__ = (
        UniqueConstraint(
            "market",
            "version_code",
            name="uq_atpv_market_version_code",
        ),
        Index("ix_atpv_market_status", "market", "status"),
        {"schema": "operation"},
    )

    process_version_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    broker_code: Mapped[str] = mapped_column(String(20), nullable=False)
    version_code: Mapped[str] = mapped_column(String(64), nullable=False)
    version_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text(f"'{STATUS_ACTIVE}'")
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    git_commit: Mapped[str | None] = mapped_column(String(40))
    change_summary: Mapped[str | None] = mapped_column(Text)
    change_reason: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    config_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    component_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    evidence_refs_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'system'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AutoTradingLogicVersionEntity(Base):
    __tablename__ = "autotrading_logic_version"
    __table_args__ = (
        UniqueConstraint(
            "market",
            "component_type",
            "version_code",
            name="uq_atlv_market_component_version",
        ),
        Index("ix_atlv_market_component", "market", "component_type"),
        {"schema": "operation"},
    )

    logic_version_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    component_type: Mapped[str] = mapped_column(String(40), nullable=False)
    version_code: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_identifier: Mapped[str | None] = mapped_column(String(120))
    rule_version: Mapped[str | None] = mapped_column(String(64))
    module_path: Mapped[str | None] = mapped_column(String(240))
    git_commit: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text(f"'{STATUS_ACTIVE}'")
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    rule_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    change_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AutoTradingProcessComponentLinkEntity(Base):
    """Immutable composition: process version ↔ logic versions."""

    __tablename__ = "autotrading_process_component_link"
    __table_args__ = (
        UniqueConstraint(
            "process_version_id",
            "component_type",
            name="uq_atpcl_process_component",
        ),
        {"schema": "operation"},
    )

    link_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    process_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    logic_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    component_type: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AutoTradingProcessChangeEntity(Base):
    __tablename__ = "autotrading_process_change"
    __table_args__ = (
        Index("ix_atpc_market_deployed", "market", "deployed_at"),
        {"schema": "operation"},
    )

    change_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    component: Mapped[str | None] = mapped_column(String(40))
    before_version_code: Mapped[str | None] = mapped_column(String(64))
    after_version_code: Mapped[str | None] = mapped_column(String(64))
    before_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    after_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    change_summary: Mapped[str] = mapped_column(Text, nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text)
    git_commit: Mapped[str | None] = mapped_column(String(40))
    evidence_refs_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    real_policy_changed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AutoTradingExecutionTraceEntity(Base):
    __tablename__ = "autotrading_execution_trace"
    __table_args__ = (
        Index("ix_atet_market_symbol_created", "market", "symbol", "created_at"),
        Index("ix_atet_process_version", "process_version_id"),
        {"schema": "operation"},
    )

    trace_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    broker_code: Mapped[str] = mapped_column(String(20), nullable=False)
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    process_version_id: Mapped[int | None] = mapped_column(BigInteger)
    completeness: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text(f"'{TRACE_UNKNOWN}'")
    )
    outcome: Mapped[str | None] = mapped_column(String(40))
    selection_id: Mapped[int | None] = mapped_column(BigInteger)
    slot_id: Mapped[int | None] = mapped_column(BigInteger)
    buy_order_id: Mapped[int | None] = mapped_column(BigInteger)
    sell_order_id: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AutoTradingTraceEventEntity(Base):
    __tablename__ = "autotrading_trace_event"
    __table_args__ = (
        UniqueConstraint(
            "trace_id",
            "stage",
            "event_type",
            "occurred_at",
            name="uq_atte_trace_stage_type_at",
        ),
        Index("ix_atte_trace_id", "trace_id"),
        {"schema": "operation"},
    )

    trace_event_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    trace_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80))
    summary: Mapped[str | None] = mapped_column(Text)
    process_version_id: Mapped[int | None] = mapped_column(BigInteger)
    logic_version_id: Mapped[int | None] = mapped_column(BigInteger)
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    output_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    source_refs_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
