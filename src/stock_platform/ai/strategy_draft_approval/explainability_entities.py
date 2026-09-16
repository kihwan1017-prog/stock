"""STEP 12-14 — Strategy Explainability & Decision Evidence 저장.

기존 검증 Report(Backtest/Performance/Walk-Forward/Quality Gate/
Parameter Sensitivity/Monte Carlo/Portfolio Validation) 스키마는 전부
"그 자신의 검증 결과"만 담는 구조라 "여러 Report를 사람이 이해할 수 있게
재구성한 설명 + Evidence Reference + Completeness/Decision Summary"를
담을 수 없어(§ 완료보고 Migration 항목) 최소 컬럼의 새 불변 테이블을
추가한다. 참조하는 각 Report ID는 FK를 두지 않는다 — Quality Gate/
Parameter Sensitivity/Monte Carlo/Portfolio Validation 중 어떤 것도
선택되지 않을 수 있고(전부 nullable), 조합도 자유로워 다대다에 가깝다
(이미 STEP12-13이 같은 이유로 JSONB 배열을 택한 전례를 따른다 — 다만
여기서는 각 Report 인스턴스 자체가 1:1이라 nullable BigInteger 컬럼으로
충분하다)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyExplainabilityReportEntity(Base):
    """승인 Strategy Definition + 기존 검증 Report들을 사람이 이해할 수
    있게 재구성한 설명(1회 생성 = 1행, 불변 — UPDATE API 없음)."""

    __tablename__ = "strategy_explainability_report"
    __table_args__ = (
        Index(
            "ux_explainability_report_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        {"schema": "trading"},
    )

    explainability_report_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_explainability_report_strategy_definition",
        ),
        nullable=False,
        index=True,
    )
    backtest_run_id: Mapped[int | None] = mapped_column(BigInteger)
    walk_forward_run_id: Mapped[int | None] = mapped_column(BigInteger)
    quality_gate_report_id: Mapped[int | None] = mapped_column(BigInteger)
    parameter_sensitivity_report_id: Mapped[int | None] = mapped_column(BigInteger)
    monte_carlo_report_id: Mapped[int | None] = mapped_column(BigInteger)
    portfolio_validation_report_id: Mapped[int | None] = mapped_column(BigInteger)

    explanation_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    explanation_language: Mapped[str] = mapped_column(String(10), nullable=False)

    strategy_overview_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rule_explanation_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    backtest_evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    walk_forward_evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    quality_gate_evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sensitivity_evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    monte_carlo_evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    portfolio_evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decision_checklist_payload: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    evidence_reference_payload: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    missing_evidence_payload: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    decision_summary_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    completeness_score: Mapped[Any] = mapped_column(Numeric(6, 2), nullable=False)
    completeness_status: Mapped[str] = mapped_column(String(20), nullable=False)

    assisted_interpretation_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    provenance_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    template_version: Mapped[str] = mapped_column(String(20), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    report_input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
