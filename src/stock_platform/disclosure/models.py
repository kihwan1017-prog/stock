from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class DartCorp(Base):
    """DART 기업 고유번호 마스터."""

    __tablename__ = "dart_corp"
    __table_args__ = (
        Index("ix_dart_corp_stock_code", "stock_code"),
        {"schema": "disclosure"},
    )

    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    corp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    modify_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


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
    receipt_no: Mapped[str] = mapped_column(String(20), nullable=False)
    corp_code: Mapped[str] = mapped_column(String(8), nullable=False)
    corp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_name: Mapped[str] = mapped_column(String(500), nullable=False)
    filer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    remark: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'OTHER'"),
    )
    importance_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default=text("0"),
    )
    is_correction: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    related_receipt_no: Mapped[str | None] = mapped_column(
        String(20),
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
