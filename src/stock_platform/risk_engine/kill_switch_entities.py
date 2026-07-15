from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class KillSwitchEntity(Base):
    __tablename__ = "kill_switch"
    __table_args__ = {"schema": "operation"}

    kill_switch_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    scope_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        unique=True,
        server_default=text("'GLOBAL'"),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    activated_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deactivated_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class KillSwitchHistoryEntity(Base):
    __tablename__ = "kill_switch_history"
    __table_args__ = {"schema": "operation"}

    kill_switch_history_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    scope_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    action_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    actor: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
