"""Persistent research feature epoch — restart/process safe."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from stock_platform.database.base import Base


class ResearchFeatureEpochEntity(Base):
    """feature별 고정 deploy epoch (호출마다 now() 금지)."""

    __tablename__ = "research_feature_epoch"
    __table_args__ = {"schema": "operation"}

    feature_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    epoch_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def get_or_create_feature_epoch(
    session: Session,
    *,
    feature_key: str,
    seed_epoch: datetime,
    seed_source: str,
) -> tuple[datetime, str]:
    """기존 row 유지 — seed로 덮어쓰지 않음 (IMMUTABLE)."""

    row = session.scalar(
        select(ResearchFeatureEpochEntity).where(
            ResearchFeatureEpochEntity.feature_key == feature_key
        )
    )
    if row is not None:
        return row.epoch_at, str(row.source)
    row = ResearchFeatureEpochEntity(
        feature_key=feature_key,
        epoch_at=seed_epoch,
        source=seed_source,
        note="bootstrap seed — do not mutate historical excluded cohorts",
    )
    session.add(row)
    session.flush()
    return row.epoch_at, str(row.source)
