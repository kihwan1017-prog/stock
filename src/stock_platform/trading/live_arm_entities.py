"""STEP 8-8 — LIVE ARM 이벤트 Entity."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class LiveArmEvent(Base):
    __tablename__ = "live_arm_event"
    __table_args__ = {"schema": "trading"}

    live_arm_event_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="CASCADE",
            name="fk_live_arm_event_uba",
        ),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    arm_token_hash: Mapped[str | None] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    detail_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default=text("'{}'::json")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
