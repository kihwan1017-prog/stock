"""STEP 12-12 — Monte Carlo Simulation 보고서 저장.

기존 backtest_run.parameters(Backtest Provenance 전용)/strategy_performance
_run.result_payload(P&L 지표 전용)/strategy_quality_gate_report(Rule PASS/
WARNING/FAIL 전용)/parameter_sensitivity_report(Variation 목록 전용) 모두
스키마 목적이 달라 "Trade 재표본화 집계 + Percentile/Confidence Interval +
대표 Simulation + Risk of Ruin + Robustness Score"라는 이번 STEP의 내용을
자연스럽게 담을 수 없어(조사 결과, § 완료보고 Migration 항목 참고) 최소
컬럼의 새 불변 테이블을 추가한다. 1000~10000개 개별 Simulation 원본은
저장하지 않고 집계 결과 + 대표 Simulation(Worst/Median/Best)만 저장한다."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
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


class MonteCarloSimulationReportEntity(Base):
    """승인 Strategy Definition의 기존 Backtest Trade 결과를 재표본화한
    Monte Carlo Simulation 결과(1회 실행 = 1행, 불변 — UPDATE API 없음)."""

    __tablename__ = "monte_carlo_simulation_report"
    __table_args__ = (
        Index(
            "ux_monte_carlo_report_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        {"schema": "trading"},
    )

    monte_carlo_report_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_monte_carlo_report_strategy_definition",
        ),
        nullable=False,
        index=True,
    )
    backtest_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "backtest.backtest_run.backtest_run_id",
            ondelete="RESTRICT",
            name="fk_monte_carlo_report_backtest_run",
        ),
        nullable=False,
    )
    simulation_method: Mapped[str] = mapped_column(String(30), nullable=False)
    simulation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    random_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confidence_level: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    ruin_threshold_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    block_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_simulation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_simulation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_of_ruin_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    robustness_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    monte_carlo_status: Mapped[str] = mapped_column(String(30), nullable=False)
    percentile_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence_interval_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    representative_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    failure_summary_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    report_input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
