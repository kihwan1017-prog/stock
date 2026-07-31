"""STEP 12-11 — Parameter Sensitivity Analysis 보고서 저장.

기존 backtest_run.parameters(Backtest Provenance 전용)/strategy_performance
_run.result_payload(P&L 지표 전용)/strategy_quality_gate_report(Rule
PASS/WARNING/FAIL 전용)는 모두 스키마 목적이 달라 "Parameter Variation
목록 + 각 Variation의 KPI + Robustness Score + Stable Range + Performance
Cliff"라는 이번 STEP의 내용을 자연스럽게 담을 수 없어(조사 결과, § 완료보고
Migration 항목 참고) 최소 컬럼의 새 불변 테이블을 추가한다. 생성 후
UPDATE하지 않으며(재평가는 새 행), 각 Variation이 실제 실행한 Backtest
Run은 새 Backtest Table을 만들지 않고 기존 backtest.backtest_run을
그대로 가리킨다(variation_results JSONB 내부에 backtest_run_id로 참조)."""

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


class ParameterSensitivityReportEntity(Base):
    """승인 Strategy Definition에 대한 Parameter Sensitivity 분석 결과(1회
    실행 = 1행, 불변 — UPDATE API를 만들지 않는다)."""

    __tablename__ = "parameter_sensitivity_report"
    __table_args__ = (
        Index(
            "ux_parameter_sensitivity_report_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        {"schema": "trading"},
    )

    parameter_sensitivity_report_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_parameter_sensitivity_report_strategy_definition",
        ),
        nullable=False,
        index=True,
    )
    base_backtest_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "backtest.backtest_run.backtest_run_id",
            ondelete="RESTRICT",
            name="fk_parameter_sensitivity_report_base_backtest_run",
        ),
        nullable=False,
    )
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    robustness_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    sensitivity_status: Mapped[str] = mapped_column(String(30), nullable=False)
    successful_variation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_variation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    parameter_specification: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    variation_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    variation_results: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    sensitivity_analytics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    stable_range: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    performance_cliffs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    status_reason: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
