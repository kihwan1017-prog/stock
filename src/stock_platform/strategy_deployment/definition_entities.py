"""STEP 8-3 — 전략 정의·계좌 연결 Entity."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyDefinitionEntity(Base):
    """전략 소유권 루트 — SYSTEM 공용 / USER 개인."""

    __tablename__ = "strategy_definition"
    __table_args__ = {"schema": "trading"}

    strategy_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    strategy_code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    market_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'STOCK'")
    )
    owner_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'SYSTEM'")
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="RESTRICT",
            name="fk_strategy_definition_user",
        ),
        nullable=True,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'PRIVATE'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    parameter_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[str | None] = mapped_column(String(100))
    updated_by: Mapped[str | None] = mapped_column(String(100))
    # 승인 메타 — RBAC Role 아님 ('operator' 보존)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    published_by: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    source_strategy_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="SET NULL",
            name="fk_strategy_definition_source",
        ),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
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


class AccountStrategyLinkEntity(Base):
    """계좌↔전략 연결 (Paper 또는 UserBrokerAccount 중 하나)."""

    __tablename__ = "account_strategy_link"
    __table_args__ = {"schema": "trading"}

    account_strategy_link_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="CASCADE",
            name="fk_account_strategy_link_strategy",
        ),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="CASCADE",
            name="fk_account_strategy_link_user",
        ),
        nullable=False,
    )
    paper_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.paper_account.account_id",
            ondelete="CASCADE",
            name="fk_account_strategy_link_paper",
        ),
    )
    user_broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="CASCADE",
            name="fk_account_strategy_link_uba",
        ),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str | None] = mapped_column(String(100))
