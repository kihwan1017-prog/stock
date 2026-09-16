"""STEP 12-15 — Decision Package & Human Decision 저장.

이미 생성된 Strategy Definition/Approval Snapshot/Backtest/Performance/
Walk-Forward/Quality Gate/Parameter Sensitivity/Monte Carlo/Portfolio
Validation/Explainability 결과를 하나의 동결된 Decision Package로
묶는다. 기존 검증 Report 스키마는 전부 "자기 자신의 검증 결과"만 담는
구조라 여러 Report를 가로지르는 승인 검토 묶음 + 사람의 결정을 담을 수
없어(§ 완료보고 Migration 항목) 최소 신규 불변 테이블 2개를 추가한다.

Decision Package와 Human Decision을 별도 테이블로 분리한다 — Package
생성만으로는 Strategy 상태를 변경하지 않고(승인 검토용 Evidence
묶음일 뿐), Human Decision(불변 기록)이 있어야 사람의 최종 결정이 남는다.
둘 다 실제 Promotion Commit/Candidate Lifecycle 변경을 수행하지 않는다
(Promotion Readiness 상태만 기록 — 다음 STEP의 명시적 Commit 입력)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class StrategyDecisionPackageEntity(Base):
    """승인 검토용 Evidence 묶음(1회 생성 = 1행, 불변 — UPDATE API 없음)."""

    __tablename__ = "strategy_decision_package"
    __table_args__ = (
        Index(
            "ux_decision_package_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        {"schema": "trading"},
    )

    package_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_decision_package_strategy_definition",
        ),
        nullable=False,
        index=True,
    )
    explainability_report_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quality_gate_report_id: Mapped[int | None] = mapped_column(BigInteger)
    parameter_sensitivity_report_id: Mapped[int | None] = mapped_column(BigInteger)
    monte_carlo_report_id: Mapped[int | None] = mapped_column(BigInteger)
    portfolio_validation_report_id: Mapped[int | None] = mapped_column(BigInteger)

    package_note: Mapped[str | None] = mapped_column(Text)
    package_status: Mapped[str] = mapped_column(String(30), nullable=False)

    required_evidence_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provenance_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    explainability_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blocking_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    human_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    readiness_reason_codes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)

    # Snapshot / Provenance(Stale Detection 기준선).
    strategy_definition_version: Mapped[int | None] = mapped_column(Integer)
    definition_hash: Mapped[str | None] = mapped_column(String(64))
    executable_hash: Mapped[str | None] = mapped_column(String(64))
    approval_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    selected_report_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    selected_report_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    explainability_input_hash: Mapped[str | None] = mapped_column(String(64))
    evidence_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checklist_template_payload: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)

    checklist_template_version: Mapped[str] = mapped_column(String(20), nullable=False)
    package_algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    package_input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    requester_id: Mapped[int | None] = mapped_column(BigInteger)
    package_created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StrategyHumanDecisionEntity(Base):
    """사람이 내린 불변 최종 결정(1 Package = 최종 Decision 1개, 불변 —
    UPDATE API 없음. 재검토가 필요하면 새 Package/새 Decision을 만든다)."""

    __tablename__ = "strategy_human_decision"
    __table_args__ = (
        Index(
            "ux_human_decision_package_id",
            "package_id",
            unique=True,
        ),
        Index(
            "ux_human_decision_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        {"schema": "trading"},
    )

    decision_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_decision_package.package_id",
            ondelete="RESTRICT",
            name="fk_human_decision_package",
        ),
        nullable=False,
    )
    strategy_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    decision_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    checklist_payload: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    acknowledged_warnings_payload: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)

    promotion_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    promotion_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promotion_readiness_hash: Mapped[str | None] = mapped_column(String(64))

    requester_id: Mapped[int | None] = mapped_column(BigInteger)
    package_created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(100), nullable=False)
    same_actor_warning: Mapped[bool] = mapped_column(Boolean, nullable=False)

    decision_input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
