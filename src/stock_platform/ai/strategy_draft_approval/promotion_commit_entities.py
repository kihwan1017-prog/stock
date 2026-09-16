"""STEP 12-16 — Promotion Commit 저장.

Strategy Definition이 "검토 완료된 Candidate 단계에서 Promoted 단계로
이동했다"는 불변 기록. Activation/Deployment/Runtime 등록은 전혀
포함하지 않는다(다음 STEP의 별도 검토 대상).

Lifecycle 관련 설계 결정(중요): 이 Report는 `ai.candidate_lifecycle
.lifecycle_status`를 직접 전이시키지 않는다 — 조사 결과 그 필드의
`PROMOTED`는 STEP11 "AI Candidate Promotion Gateway"(Candidate가
Strategy Request 생성 자격을 얻었다는 훨씬 이른 단계의 의미)이고, 이미
이 파이프라인의 모든 Strategy Definition은 그 단계를 통과한 상태다(전제
조건). STEP12-16의 "Promotion"은 그보다 훨씬 뒤(Backtest/Quality Gate/
Explainability/Decision Package 검토 완료) 단계의 완전히 다른 개념이라,
같은 필드에 같은 값(PROMOTED)을 다시 쓰면 두 서로 다른 Lifecycle 개념이
충돌한다. 따라서 `previous_lifecycle_status`는 Commit 시점의
candidate_lifecycle.lifecycle_status 스냅샷(정보용, 차단 판정에는
기존 값을 그대로 읽어 사용)이고, `committed_lifecycle_status`는 이
Strategy Definition 고유의 Promotion 결과 라벨("PROMOTED")이며, 이
테이블 자신에만 기록된다(기존 candidate_lifecycle 테이블은 건드리지
않음 — 새 Lifecycle Enum 값을 만들지도 않음, 기존 값을 다른 의미로
전용하지도 않음)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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


class StrategyPromotionCommitEntity(Base):
    """Strategy Definition의 불변 Promotion Commit 기록(1 Strategy = 유효
    Commit 1개, 1 Human Decision = Commit 1개, 둘 다 UNIQUE 제약으로
    강제). UPDATE API 없음 — 취소/되돌리기는 이번 STEP에서 구현하지
    않는다(기존 Lifecycle의 REVOKE/SUPERSEDE/ARCHIVE 정책을 재사용)."""

    __tablename__ = "strategy_promotion_commit"
    __table_args__ = (
        Index(
            "ux_promotion_commit_strategy_id",
            "strategy_definition_id",
            unique=True,
        ),
        Index(
            "ux_promotion_commit_human_decision_id",
            "human_decision_id",
            unique=True,
        ),
        Index(
            "ux_promotion_commit_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        {"schema": "trading"},
    )

    promotion_commit_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_definition.strategy_id",
            ondelete="RESTRICT",
            name="fk_promotion_commit_strategy_definition",
        ),
        nullable=False,
    )
    candidate_id: Mapped[int | None] = mapped_column(BigInteger)
    strategy_request_id: Mapped[int | None] = mapped_column(BigInteger)
    approval_id: Mapped[int | None] = mapped_column(BigInteger)
    decision_package_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_decision_package.package_id",
            ondelete="RESTRICT",
            name="fk_promotion_commit_decision_package",
        ),
        nullable=False,
    )
    human_decision_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.strategy_human_decision.decision_id",
            ondelete="RESTRICT",
            name="fk_promotion_commit_human_decision",
        ),
        nullable=False,
    )

    previous_lifecycle_status: Mapped[str | None] = mapped_column(String(40))
    committed_lifecycle_status: Mapped[str] = mapped_column(String(40), nullable=False)

    strategy_definition_version: Mapped[int | None] = mapped_column(Integer)
    definition_hash: Mapped[str | None] = mapped_column(String(64))
    executable_hash: Mapped[str | None] = mapped_column(String(64))
    approval_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    package_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    promotion_readiness_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    source_report_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance_snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    commit_reason: Mapped[str] = mapped_column(Text, nullable=False)
    confirmation_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    committed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    promotion_commit_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
