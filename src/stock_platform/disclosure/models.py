from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Identity,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class DartDisclosure(Base):
    __tablename__ = "dart_disclosure"
    __table_args__ = (
        UniqueConstraint(
            "receipt_no",
            name="uq_dart_disclosure_receipt_no",
        ),
        {"schema": "disclosure"},
    )

    disclosure_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    receipt_no: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    corp_code: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )
    corp_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    stock_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    report_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    filer_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    receipt_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    remark: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
