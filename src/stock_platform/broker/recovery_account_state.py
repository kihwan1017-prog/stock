"""STEP 8-4 — Recovery 계좌 상태·Lock Entity."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class BrokerRecoveryAccountStateEntity(Base):
    """계좌별 Recovery Lock·거래 일시차단 상태."""

    __tablename__ = "broker_recovery_account_state"
    __table_args__ = (
        CheckConstraint(
            "recovery_status IN ("
            "'IDLE','RUNNING','FAILED','MANUAL_REVIEW','SUCCESS')",
            name="ck_recovery_account_status",
        ),
        {"schema": "operation"},
    )

    recovery_account_state_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    paper_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id",
            ondelete="CASCADE",
            name="fk_recovery_state_paper",
        ),
    )
    user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="CASCADE",
            name="fk_recovery_state_uba",
        ),
    )
    recovery_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'IDLE'"),
    )
    trading_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    lock_holder: Mapped[str | None] = mapped_column(String(100))
    lock_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_recovery_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "operation.broker_recovery_run.broker_recovery_run_id",
            ondelete="SET NULL",
            name="fk_recovery_state_run",
        ),
    )
    last_error_summary: Mapped[str | None] = mapped_column(Text)
    # STEP 8-5-3 — Scheduler 재시도
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    auto_retry_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # STEP 8-5-8 — Rate Limit defer meta
    next_retry_reason: Mapped[str | None] = mapped_column(String(60))
    rate_limit_endpoint_group: Mapped[str | None] = mapped_column(
        String(40)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
