"""STEP 12-10 — Strategy Quality Gate 평가 결과 저장.

기존 저장 구조(backtest_run.parameters, strategy_performance_run
.result_payload)로는 "특정 시점의 Rule 기반 PASS/WARNING/FAIL 평가 +
Recommendation + Risk Grade" 결과를 자연스럽게 담을 수 없어(내용이 전혀
다른 스키마 — StrategyPerformanceMetricEntity는 P&L 지표 전용) 최소
컬럼의 새 테이블을 추가한다(§ 완료보고 Migration 항목에 근거 명시).
새 Backtest/Walk-Forward 구조는 만들지 않는다 — 평가 대상 Run만 FK로
가리키고, 실제 KPI/Score는 여전히 기존 Backtest/Performance/Walk-Forward
저장소에서 조회한다."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyQualityGateReportEntity(Base):
    """승인 Strategy Definition에 대한 자동 품질 심사 결과(1회 평가 = 1행)."""

    __tablename__ = "strategy_quality_gate_report"
    __table_args__ = ({"schema": "trading"},)

    quality_gate_report_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_quality_gate_report_strategy_definition",
        ),
        nullable=False,
        index=True,
    )
    backtest_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "backtest.backtest_run.backtest_run_id",
            ondelete="SET NULL",
            name="fk_quality_gate_report_backtest_run",
        ),
        nullable=True,
    )
    walk_forward_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_performance_run.strategy_performance_run_id",
            ondelete="SET NULL",
            name="fk_quality_gate_report_walk_forward_run",
        ),
        nullable=True,
    )
    recommendation: Mapped[str] = mapped_column(String(30), nullable=False)
    risk_grade: Mapped[str] = mapped_column(String(20), nullable=False)
    rules_payload: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    threshold_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk_grade_reason: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
