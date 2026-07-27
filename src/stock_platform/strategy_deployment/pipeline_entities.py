from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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


class StrategyDeploymentPipelineEntity(Base):
    __tablename__ = "strategy_deployment_pipeline"
    __table_args__ = {"schema": "trading"}

    strategy_deployment_pipeline_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    strategy_selection_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.strategy_selection_run.strategy_selection_run_id",
            ondelete="RESTRICT",
            name="fk_deployment_pipeline_selection",
        ),
        nullable=False,
    )
    strategy_approval_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_approval_run.strategy_approval_run_id",
            ondelete="SET NULL",
            name="fk_deployment_pipeline_approval",
        ),
        nullable=True,
    )
    strategy_deployment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment.strategy_deployment_id",
            ondelete="SET NULL",
            name="fk_deployment_pipeline_deployment",
        ),
        nullable=True,
    )
    strategy_runtime_switch_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_runtime_switch.strategy_runtime_switch_id",
            ondelete="SET NULL",
            name="fk_deployment_pipeline_runtime_switch",
        ),
        nullable=True,
    )
    strategy_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    market_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    symbol: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    requested_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    detail_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
