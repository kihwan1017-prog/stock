"""STEP 8-5-6 — broker_recovery_lock Entity."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class BrokerRecoveryLockEntity(Base):
    __tablename__ = "broker_recovery_lock"
    __table_args__ = (
        UniqueConstraint(
            "lock_scope_key",
            name="uq_broker_recovery_lock_scope",
        ),
        {"schema": "operation"},
    )

    broker_recovery_lock_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    lock_scope_key: Mapped[str] = mapped_column(
        String(80), nullable=False
    )
    account_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    account_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    user_broker_account_id: Mapped[int | None] = mapped_column(BigInteger)
    paper_account_id: Mapped[int | None] = mapped_column(BigInteger)
    broker_code: Mapped[str] = mapped_column(String(30), nullable=False)
    market_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'ALL'")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'FREE'")
    )
    owner_instance_id: Mapped[str | None] = mapped_column(String(200))
    lease_id: Mapped[str | None] = mapped_column(String(64))
    fencing_token: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0"), default=0
    )
    acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    release_reason: Mapped[str | None] = mapped_column(String(40))
    recovery_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "operation.broker_recovery_run.broker_recovery_run_id",
            ondelete="SET NULL",
            name="fk_recovery_lock_run",
        ),
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

    def as_admin_dict(self) -> dict[str, Any]:
        owner = self.owner_instance_id or ""
        masked_owner = None
        if owner:
            parts = owner.split(":")
            masked_owner = (
                f"{parts[1][:12] if len(parts) > 1 else owner[:12]}:…:"
                f"{parts[-1][:8] if parts else ''}"
            )
        return {
            "lock_id": int(self.broker_recovery_lock_id),
            "lock_scope_key": self.lock_scope_key,
            "account_kind": self.account_kind,
            "account_id": int(self.account_id),
            "user_broker_account_id": self.user_broker_account_id,
            "paper_account_id": self.paper_account_id,
            "broker_code": self.broker_code,
            "market_type": self.market_type,
            "status": self.status,
            "owner_instance_masked": masked_owner,
            "fencing_token": int(self.fencing_token),
            "acquired_at": (
                self.acquired_at.isoformat() if self.acquired_at else None
            ),
            "heartbeat_at": (
                self.heartbeat_at.isoformat()
                if self.heartbeat_at
                else None
            ),
            "lease_expires_at": (
                self.lease_expires_at.isoformat()
                if self.lease_expires_at
                else None
            ),
            "release_reason": self.release_reason,
            "recovery_run_id": self.recovery_run_id,
            "stale": bool(
                self.status == "HELD"
                and self.lease_expires_at is not None
                and self.lease_expires_at < datetime.now(timezone.utc)
            ),
        }
