"""STEP 11-11 — Queue eligibility (trading/order/runtime/scheduler import 금지)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_assessment.entities import AICandidateAssessmentEntity
from stock_platform.ai.candidate_consensus.entities import (
    AICandidateConsensusConflictEntity,
    AICandidateConsensusEntity,
)
from stock_platform.ai.candidate_recommendation_queue.constants import (
    APPROVED_SOURCE_REVIEW,
    ELIGIBILITY_VERSION,
    FORBIDDEN_TRADING_KEYS,
    QUEUEABLE_ASSESSMENT_STATUSES,
    QUEUEABLE_CONSENSUS_STATUSES,
    REFERENCE_DISCLAIMER,
    SOURCE_TYPES,
)


def _has_forbidden_trading_keys(payload: Any, path: str = "") -> list[str]:
    """Safe Result 내 매매 지시 키 탐지."""
    hits: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            full = f"{path}.{key}" if path else str(key)
            if str(key).lower() in FORBIDDEN_TRADING_KEYS:
                hits.append(full)
            hits.extend(_has_forbidden_trading_keys(value, full))
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            hits.extend(_has_forbidden_trading_keys(item, f"{path}[{idx}]"))
    return hits


class AIRecommendationQueueEligibilityService:
    """
    Assessment/Consensus 소스 적격성 검증.

    Safety:
    - strategy.candidate INSERT 금지
    - screener.persistence_models.CandidateResult 는 READ-ONLY (기존 후보 충돌 확인)
    - trading/order/runtime/scheduler import 금지
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def validate_source(
        self,
        *,
        source_type: str,
        candidate_assessment_id: int | None = None,
        candidate_consensus_id: int | None = None,
        allow_existing_candidate_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        reasons: list[str] = []
        warnings: list[str] = []
        snapshot: dict[str, Any] = {
            "source_type": source_type,
            "eligibility_version": ELIGIBILITY_VERSION,
        }

        if source_type not in SOURCE_TYPES:
            reasons.append("INVALID_SOURCE_TYPE")
            return self._result(False, reasons, warnings, snapshot)

        if source_type == "CANDIDATE_ASSESSMENT":
            if candidate_assessment_id is None or candidate_consensus_id is not None:
                reasons.append("SOURCE_XOR_VIOLATION")
                return self._result(False, reasons, warnings, snapshot)
            source = self._load_assessment(candidate_assessment_id)
            if source is None:
                reasons.append("SOURCE_NOT_FOUND")
                return self._result(False, reasons, warnings, snapshot)
            if source.assessment_status not in QUEUEABLE_ASSESSMENT_STATUSES:
                reasons.append(f"ASSESSMENT_STATUS_{source.assessment_status}")
            if source.superseded_at is not None:
                reasons.append("SOURCE_SUPERSEDED")
            if not source.safe_result:
                reasons.append("SAFE_RESULT_MISSING")
            if source.source_missing:
                reasons.append("SOURCE_MISSING")
            if (source.data_quality or "").upper() == "INVALID":
                reasons.append("DATA_QUALITY_INVALID")
            review = (source.review_decision or "").upper()
            if review not in APPROVED_SOURCE_REVIEW:
                reasons.append("SOURCE_REVIEW_REQUIRED")
            trading_hits = _has_forbidden_trading_keys(source.safe_result)
            if trading_hits:
                reasons.append("TRADING_LANGUAGE_DETECTED")
                snapshot["trading_language_paths"] = trading_hits[:20]
            # 동일 instrument에 유효 Consensus가 있으면 Assessment 직접 등록 기본 차단
            if self._active_consensus_for_instrument(
                instrument_id=source.instrument_id,
                symbol=source.symbol,
                evidence_bundle_hash=source.evidence_bundle_hash,
            ):
                reasons.append("CONSENSUS_PREFERRED")
            snapshot.update(self._assessment_snapshot(source))

        else:
            if candidate_consensus_id is None or candidate_assessment_id is not None:
                reasons.append("SOURCE_XOR_VIOLATION")
                return self._result(False, reasons, warnings, snapshot)
            source = self._load_consensus(candidate_consensus_id)
            if source is None:
                reasons.append("SOURCE_NOT_FOUND")
                return self._result(False, reasons, warnings, snapshot)
            if source.consensus_status not in QUEUEABLE_CONSENSUS_STATUSES:
                reasons.append(f"CONSENSUS_STATUS_{source.consensus_status}")
            if source.superseded_at is not None:
                reasons.append("SOURCE_SUPERSEDED")
            if not source.safe_result:
                reasons.append("SAFE_RESULT_MISSING")
            if int(source.included_count or 0) < 2:
                reasons.append("INSUFFICIENT_MEMBERS")
            review = (source.review_decision or "").upper()
            if review not in APPROVED_SOURCE_REVIEW:
                reasons.append("SOURCE_REVIEW_REQUIRED")
            if self._has_critical_conflict(source.consensus_id):
                reasons.append("CRITICAL_CONFLICT")
            trading_hits = _has_forbidden_trading_keys(source.safe_result)
            if trading_hits:
                reasons.append("TRADING_LANGUAGE_DETECTED")
                snapshot["trading_language_paths"] = trading_hits[:20]
            if (source.provider_diversity or "").upper() in {"LOW", "LIMITED"}:
                warnings.append("LIMITED_PROVIDER_DIVERSITY")
            snapshot.update(self._consensus_snapshot(source))

        symbol = snapshot.get("symbol") or ""
        exchange_code = snapshot.get("exchange_code") or ""
        conflict = self._check_existing_candidate(symbol, exchange_code)
        if conflict:
            snapshot["existing_candidate"] = conflict
            if allow_existing_candidate_override:
                if not override_reason or not str(override_reason).strip():
                    reasons.append("OVERRIDE_REASON_REQUIRED")
                else:
                    warnings.append("EXISTING_CANDIDATE_OVERRIDE")
                    snapshot["override_reason"] = str(override_reason).strip()[:500]
            else:
                reasons.append("EXISTING_CANDIDATE_CONFLICT")

        if not snapshot.get("source_result_hash"):
            reasons.append("SOURCE_RESULT_HASH_MISSING")
        if not snapshot.get("evidence_bundle_hash"):
            reasons.append("EVIDENCE_BUNDLE_HASH_MISSING")

        return self._result(len(reasons) == 0, reasons, warnings, snapshot)

    def _active_consensus_for_instrument(
        self,
        *,
        instrument_id: int | None,
        symbol: str,
        evidence_bundle_hash: str | None,
    ) -> bool:
        """동일 종목·증거 번들에 유효 Consensus가 있으면 Assessment 직접 등록 제한."""
        stmt = select(AICandidateConsensusEntity).where(
            AICandidateConsensusEntity.consensus_status.in_(
                QUEUEABLE_CONSENSUS_STATUSES
            ),
            AICandidateConsensusEntity.superseded_at.is_(None),
            AICandidateConsensusEntity.symbol == symbol,
        )
        if evidence_bundle_hash:
            stmt = stmt.where(
                AICandidateConsensusEntity.evidence_bundle_hash
                == evidence_bundle_hash
            )
        if instrument_id is not None:
            stmt = stmt.where(
                AICandidateConsensusEntity.instrument_id == instrument_id
            )
        return self._session.scalar(stmt.limit(1)) is not None

    def _has_critical_conflict(self, consensus_id: int) -> bool:
        row = self._session.scalar(
            select(AICandidateConsensusConflictEntity)
            .where(
                AICandidateConsensusConflictEntity.candidate_consensus_id
                == consensus_id,
                AICandidateConsensusConflictEntity.severity == "CRITICAL",
                AICandidateConsensusConflictEntity.resolution_status.in_(
                    ["UNRESOLVED", "REVIEW_REQUIRED"]
                ),
            )
            .limit(1)
        )
        return row is not None

    def _check_existing_candidate(
        self, symbol: str, exchange_code: str
    ) -> dict[str, Any] | None:
        # READ-ONLY: persistence_models SELECT만 (INSERT/UPDATE 금지)
        from stock_platform.screener.persistence_models import CandidateResult

        row = self._session.scalar(
            select(CandidateResult)
            .where(
                CandidateResult.symbol == symbol,
                CandidateResult.exchange_code == exchange_code,
            )
            .order_by(CandidateResult.created_at.desc())
            .limit(1)
        )
        if row is None:
            return None
        return {
            "result_id": row.result_id,
            "run_id": row.run_id,
            "symbol": row.symbol,
            "exchange_code": row.exchange_code,
            "rank_no": row.rank_no,
            "trade_date": row.trade_date.isoformat(),
        }

    def _load_assessment(
        self, assessment_id: int
    ) -> AICandidateAssessmentEntity | None:
        return self._session.get(AICandidateAssessmentEntity, assessment_id)

    def _load_consensus(
        self, consensus_id: int
    ) -> AICandidateConsensusEntity | None:
        return self._session.get(AICandidateConsensusEntity, consensus_id)

    @staticmethod
    def _assessment_snapshot(row: AICandidateAssessmentEntity) -> dict[str, Any]:
        return {
            "candidate_assessment_id": row.assessment_id,
            "candidate_consensus_id": None,
            "market_type": row.market_type,
            "exchange_code": row.exchange_code,
            "symbol": row.symbol,
            "instrument_id": row.instrument_id,
            "source_result_hash": row.result_hash,
            "evidence_bundle_hash": row.evidence_bundle_hash,
            "source_review_decision": row.review_decision,
            "source_quality_score": row.overall_score,
            "analytical_score": row.analytical_score,
            "risk_score": row.risk_score,
            "confidence": row.confidence,
            "agreement_level": None,
            "disagreement_level": row.conflict_status,
            "provider_diversity": row.provider_code,
            "source_status": row.assessment_status,
        }

    @staticmethod
    def _consensus_snapshot(row: AICandidateConsensusEntity) -> dict[str, Any]:
        return {
            "candidate_assessment_id": None,
            "candidate_consensus_id": row.consensus_id,
            "market_type": row.market_type,
            "exchange_code": row.exchange_code,
            "symbol": row.symbol,
            "instrument_id": row.instrument_id,
            "source_result_hash": row.result_hash,
            "evidence_bundle_hash": row.evidence_bundle_hash,
            "source_review_decision": row.review_decision,
            "source_quality_score": row.weighted_analytical_score,
            "analytical_score": row.weighted_analytical_score,
            "risk_score": row.weighted_risk_score,
            "confidence": row.weighted_confidence,
            "agreement_level": row.agreement_level,
            "disagreement_level": row.disagreement_level,
            "provider_diversity": row.provider_diversity,
            "source_status": row.consensus_status,
            "included_count": row.included_count,
        }

    @staticmethod
    def _result(
        allowed: bool,
        reasons: list[str],
        warnings: list[str],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "allowed": allowed,
            "reasons": reasons,
            "warnings": warnings,
            "snapshot": snapshot,
            "eligibility_version": ELIGIBILITY_VERSION,
            "disclaimer": REFERENCE_DISCLAIMER,
        }
