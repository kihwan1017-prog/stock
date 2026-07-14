from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Identity, Integer, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class CandidateRun(Base):
    __tablename__ = "candidate_run"
    __table_args__ = (
        UniqueConstraint("exchange_code", "as_of_date", "run_type", name="uq_candidate_run_exchange_date_type"),
        {"schema": "strategy"},
    )

    run_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    run_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'DAILY'"))
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    evaluated_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    minimum_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, server_default=text("0"))
    require_all_rules: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status_code: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'COMPLETED'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CandidateResult(Base):
    __tablename__ = "candidate_result"
    __table_args__ = (
        UniqueConstraint("run_id", "rank_no", name="uq_candidate_result_run_rank"),
        UniqueConstraint("run_id", "symbol", name="uq_candidate_result_run_symbol"),
        {"schema": "strategy"},
    )

    result_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("strategy.candidate_run.run_id", ondelete="CASCADE", name="fk_candidate_result_run_id_candidate_run"),
        nullable=False,
    )
    rank_no: Mapped[int] = mapped_column(Integer, nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    rules_passed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    all_rules_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rule_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
