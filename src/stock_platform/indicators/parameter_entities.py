"""기술지표 파라미터 설정 Entity."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class IndicatorParameterConfigEntity(Base):
    __tablename__ = "indicator_parameter_config"
    __table_args__ = {"schema": "market"}

    indicator_parameter_config_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    indicator_code: Mapped[str] = mapped_column(String(40), nullable=False)
    market_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'STOCK'")
    )
    exchange_code: Mapped[str | None] = mapped_column(String(20))
    timeframe: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'1D'")
    )
    parameter_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_by: Mapped[str | None] = mapped_column(String(100))
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
