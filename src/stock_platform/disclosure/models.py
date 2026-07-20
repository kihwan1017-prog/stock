from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
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
        Index(
            "ix_dart_disclosure_stock_receipt",
            "stock_code",
            "receipt_date",
        ),
        Index(
            "ix_dart_disclosure_corp_receipt",
            "corp_code",
            "receipt_date",
        ),
        Index(
            "ix_dart_disclosure_category_receipt",
            "category_code",
            "receipt_date",
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


class UserDisclosureState(Base):
    """사용자별 공시 읽음·북마크 상태."""

    __tablename__ = "user_disclosure_state"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "disclosure_id",
            name="uq_user_disclosure_state_user_disclosure",
        ),
        Index(
            "ix_user_disclosure_state_user_read",
            "user_id",
            "is_read",
        ),
        Index(
            "ix_user_disclosure_state_user_bookmarked",
            "user_id",
            "is_bookmarked",
        ),
        {"schema": "disclosure"},
    )

    user_disclosure_state_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="CASCADE",
            name="fk_user_disclosure_state_user",
        ),
        nullable=False,
    )
    disclosure_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "disclosure.dart_disclosure.disclosure_id",
            ondelete="CASCADE",
            name="fk_user_disclosure_state_disclosure",
        ),
        nullable=False,
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    is_bookmarked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    bookmarked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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


class DisclosureAiSummary(Base):
    """공용 공시 AI 요약 캐시 — 사용자별 중복 생성 금지."""

    __tablename__ = "disclosure_ai_summary"
    __table_args__ = (
        UniqueConstraint(
            "disclosure_id",
            "summary_type",
            "model_name",
            "prompt_version",
            "source_text_hash",
            name="uq_disclosure_ai_summary_cache",
        ),
        Index("ix_disclosure_ai_summary_status", "status"),
        Index("ix_disclosure_ai_summary_generated", "generated_at"),
        Index("ix_disclosure_ai_summary_disclosure", "disclosure_id"),
        {"schema": "disclosure"},
    )

    summary_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    disclosure_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "disclosure.dart_disclosure.disclosure_id",
            ondelete="CASCADE",
            name="fk_disclosure_ai_summary_disclosure",
        ),
        nullable=False,
    )
    summary_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'DISCLOSURE'"),
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'v1'"),
    )
    source_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'NOT_REQUESTED'"),
    )
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_points_json: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    risk_factors_json: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    financial_impacts_json: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    important_numbers_json: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    uncertainty_notes_json: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
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
