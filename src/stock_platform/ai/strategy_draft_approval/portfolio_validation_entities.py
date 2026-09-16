"""STEP 12-13 — Portfolio Validation 보고서 저장.

기존 backtest_run.parameters/strategy_performance_run.result_payload/
strategy_quality_gate_report/parameter_sensitivity_report/
monte_carlo_simulation_report 전부 단일 Strategy(또는 단일 Run) 기준
스키마라 "복수 Strategy 조합 + Correlation Matrix + Risk Contribution +
Diversification + Duplicate Exposure"라는 이번 STEP의 내용을 담을 수
없어(조사 결과) 최소 컬럼의 새 불변 테이블을 추가한다. 원시 Return
Matrix/개별 Simulation은 저장하지 않고 집계 결과와 Portfolio Equity
Curve만 저장한다."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class PortfolioValidationReportEntity(Base):
    """복수 승인 Strategy Definition의 기존 Backtest 결과를 조합한 Portfolio
    Validation 결과(1회 실행 = 1행, 불변 — UPDATE API 없음). 개별
    Strategy Definition에 대한 단일 FK를 두지 않는다(다대다 관계라
    strategy_definition_ids를 JSONB 배열로 저장 — §Provenance)."""

    __tablename__ = "portfolio_validation_report"
    __table_args__ = (
        Index(
            "ux_portfolio_validation_report_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        {"schema": "trading"},
    )

    portfolio_validation_report_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    backtest_run_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    weighting_method: Mapped[str] = mapped_column(String(30), nullable=False)
    alignment_policy: Mapped[str] = mapped_column(String(30), nullable=False)
    common_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    common_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_count: Mapped[int] = mapped_column(Integer, nullable=False)
    robustness_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False)
    weights_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    common_period_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    portfolio_kpi_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correlation_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    concentration_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk_contribution_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    diversification_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    duplicate_exposure_payload: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    portfolio_equity_payload: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    existing_validation_summary_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    robustness_breakdown_payload: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    status_reason_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    report_input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
