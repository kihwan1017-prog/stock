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


class StrategyDeploymentEntity(Base):
    __tablename__ = "strategy_deployment"
    # ACTIVE unique는 partial index (SYSTEM/USER 분리) — 테이블 UniqueConstraint 없음
    __table_args__ = ({"schema": "trading"},)

    strategy_deployment_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    strategy_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    # § STEP12-19 — STEP12-x AI Strategy 파이프라인(Backtest/Quality Gate
    # 근거 체계)으로 생성되는 Deployment는 이 컬럼이 가리키는 STEP7-x류
    # "Performance Run" 개념과 무관하므로 NULL을 허용한다(기존
    # PaperStrategyDeploymentService의 호출부는 계속 값을 채워 넣으므로
    # 하위 호환에 영향 없음).
    strategy_performance_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_performance_run.strategy_performance_run_id",
            ondelete="RESTRICT",
            name="fk_strategy_deployment_performance_run",
        ),
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
    mode_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'PAPER'"),
    )
    status_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    parameter_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    requested_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    # STEP8-3 소유권
    strategy_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="SET NULL",
            name="fk_strategy_deployment_definition",
        ),
        nullable=True,
    )
    owner_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'SYSTEM'"),
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="RESTRICT",
            name="fk_strategy_deployment_user",
        ),
        nullable=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'PUBLIC'"),
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    replaced_by_deployment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment.strategy_deployment_id",
            ondelete="SET NULL",
            name="fk_strategy_deployment_replaced_by",
        ),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class StrategyDeploymentHistoryEntity(Base):
    __tablename__ = "strategy_deployment_history"
    __table_args__ = {"schema": "trading"}

    strategy_deployment_history_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    strategy_deployment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_deployment.strategy_deployment_id",
            ondelete="CASCADE",
            name="fk_strategy_deployment_history_deployment",
        ),
        nullable=False,
    )
    action_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(
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
