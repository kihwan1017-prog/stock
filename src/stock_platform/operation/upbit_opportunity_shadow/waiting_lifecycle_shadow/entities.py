"""ORM — Waiting Lifecycle Forward Shadow Lab (research only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base
from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.constants import (
    RULE_VERSION,
    STATUS_ACTIVE,
)


class UpbitWaitingLifecycleShadowObservationEntity(Base):
    """Canonical shadow waiting observation — variant별 독립 state."""

    __tablename__ = "upbit_waiting_lifecycle_shadow_observation"
    __table_args__ = (
        UniqueConstraint(
            "user_broker_account_id",
            "variant",
            "selection_id",
            "cohort",
            name="uq_wl_shadow_obs_uba_var_sel_cohort",
        ),
        Index(
            "ix_wl_shadow_obs_uba_var_status",
            "user_broker_account_id",
            "variant",
            "status",
        ),
        Index("ix_wl_shadow_obs_symbol", "symbol"),
        Index("ix_wl_shadow_obs_enrolled", "enrolled_at"),
        {"schema": "operation"},
    )

    # Integer PK — SQLite autoincrement 호환 (PG migration은 BigIdentity)
    observation_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variant: Mapped[str] = mapped_column(String(8), nullable=False)
    cohort: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    selection_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    candidate_id: Mapped[int | None] = mapped_column(BigInteger)
    candidate_snapshot_id: Mapped[str | None] = mapped_column(String(80))
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    deployment_id: Mapped[int | None] = mapped_column(BigInteger)
    slot_id: Mapped[int | None] = mapped_column(BigInteger)
    waiting_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # shadow TTL 기준 시각 — preexisting는 enrolled_at, primary는 waiting_created_at
    ttl_anchor_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    initial_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text(f"'{STATUS_ACTIVE}'")
    )
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_candidate_id: Mapped[int | None] = mapped_column(BigInteger)
    replacement_selection_id: Mapped[int | None] = mapped_column(BigInteger)
    replacement_score: Mapped[float | None] = mapped_column(Float)
    terminal_stage: Mapped[str | None] = mapped_column(String(64))
    real_buy_filled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    shadow_expired_but_real_later_bought: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_decision: Mapped[str | None] = mapped_column(String(40))
    last_block_reason: Mapped[str | None] = mapped_column(String(80))
    consecutive_no_signal: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    evaluation_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    rule_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{RULE_VERSION}'")
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UpbitWaitingLifecycleShadowEventEntity(Base):
    """Shadow lifecycle event — coalesced to avoid amplification."""

    __tablename__ = "upbit_waiting_lifecycle_shadow_event"
    __table_args__ = (
        Index(
            "ix_wl_shadow_evt_obs_type_at",
            "observation_id",
            "event_type",
            "observed_at",
        ),
        Index("ix_wl_shadow_evt_dedupe", "dedupe_key"),
        {"schema": "operation"},
    )

    event_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    observation_id: Mapped[int | None] = mapped_column(BigInteger)
    user_broker_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variant: Mapped[str] = mapped_column(String(8), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    age_seconds: Mapped[float | None] = mapped_column(Float)
    decision: Mapped[str | None] = mapped_column(String(40))
    block_reason: Mapped[str | None] = mapped_column(String(80))
    score: Mapped[float | None] = mapped_column(Float)
    symbol: Mapped[str | None] = mapped_column(String(40))
    selection_id: Mapped[int | None] = mapped_column(BigInteger)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default=text("'{}'")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
