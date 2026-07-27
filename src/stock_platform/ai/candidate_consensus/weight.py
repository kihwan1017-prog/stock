"""STEP 11-10 — Consensus 멤버 가중치."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_consensus.constants import (
    APPROVED_REVIEW_DECISIONS,
    REFERENCE_DISCLAIMER,
)
from stock_platform.ai.review.entities import (
    AIAnalysisReviewDecisionEntity,
    AIBenchmarkRunEntity,
)


def _clamp_factor(value: float, *, low: float = 0.0, high: float = 1.5) -> float:
    return max(low, min(high, value))


class AIConsensusWeightService:
    """
    final = base(1.0) * review * scorecard * calibration * citation
            * data_quality * independence * conflict_penalty
    각 factor 0..1.5 cap, final >= 0
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def compute_weights(
        self, members_with_meta: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        warnings: list[str] = []
        weighted: list[dict[str, Any]] = []

        for member in members_with_meta:
            breakdown, member_warnings = self._compute_member(member)
            warnings.extend(member_warnings)
            weighted.append({**member, **breakdown})

        included = [m for m in weighted if m.get("included", True)]
        total_final = sum(float(m.get("final_weight") or 0) for m in included)

        if total_final <= 0 and included:
            # 가중치 합이 0이면 균등 분배 fallback
            equal = 1.0 / len(included)
            for m in included:
                m["normalized_weight"] = equal
            warnings.append("ZERO_WEIGHT_FALLBACK_EQUAL")
        else:
            for m in included:
                fw = float(m.get("final_weight") or 0)
                m["normalized_weight"] = fw / total_final if total_final else 0.0

        for m in weighted:
            if not m.get("included", True):
                m["normalized_weight"] = 0.0

        return weighted

    def _compute_member(
        self, member: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        base = 1.0

        review = self._review_factor(member.get("review_decision"))
        scorecard, score_warn = self._scorecard_factor(member)
        if score_warn:
            warnings.append(score_warn)
        calibration = self._calibration_factor(member.get("assessment_id"))
        citation = self._citation_factor(member.get("result_body") or {})
        data_quality = self._data_quality_factor(member.get("data_quality"))
        independence = self._independence_factor(
            member.get("independence_status")
        )
        conflict_penalty = self._conflict_penalty(member.get("conflict_status"))

        factors = {
            "base_weight": base,
            "review_weight": review,
            "scorecard_weight": scorecard,
            "calibration_weight": calibration,
            "citation_weight": citation,
            "data_quality_weight": data_quality,
            "independence_weight": independence,
            "conflict_penalty": conflict_penalty,
        }

        final = base
        for key in (
            "review_weight",
            "scorecard_weight",
            "calibration_weight",
            "citation_weight",
            "data_quality_weight",
            "independence_weight",
            "conflict_penalty",
        ):
            final *= factors[key]

        final = max(0.0, final)
        breakdown = {
            **factors,
            "final_weight": final,
            "weight_breakdown": factors,
        }
        return breakdown, warnings

    @staticmethod
    def _review_factor(review_decision: str | None) -> float:
        if review_decision in APPROVED_REVIEW_DECISIONS:
            if review_decision == "APPROVED_WITH_WARNINGS":
                return _clamp_factor(0.85)
            return _clamp_factor(1.0)
        if review_decision in {None, "PENDING", "REVIEW_PENDING"}:
            return _clamp_factor(0.6)
        return _clamp_factor(0.0)

    def _scorecard_factor(
        self, member: dict[str, Any]
    ) -> tuple[float, str | None]:
        provider = (member.get("provider_code") or "").lower()
        model = member.get("model") or ""
        if not provider:
            return _clamp_factor(0.7), "UNSCORED_PROVIDER"

        run = self._session.scalar(
            select(AIBenchmarkRunEntity)
            .where(
                AIBenchmarkRunEntity.provider_code == provider,
                AIBenchmarkRunEntity.model == model,
                AIBenchmarkRunEntity.status == "COMPLETED",
            )
            .order_by(AIBenchmarkRunEntity.benchmark_run_id.desc())
            .limit(1)
        )
        if run is None or not run.metrics:
            return _clamp_factor(0.7), "UNSCORED_PROVIDER"

        accuracy = run.metrics.get("accuracy") or run.metrics.get("avg_score")
        if accuracy is None:
            return _clamp_factor(0.7), "UNSCORED_PROVIDER"
        try:
            score = float(accuracy)
        except (TypeError, ValueError):
            return _clamp_factor(0.7), "UNSCORED_PROVIDER"
        # 0~1 또는 0~5 스케일 모두 수용
        if score > 1.0:
            score = score / 5.0
        return _clamp_factor(0.5 + score * 0.5), None

    def _calibration_factor(self, assessment_id: int | None) -> float:
        if assessment_id is None:
            return _clamp_factor(0.7)
        decision = self._session.scalar(
            select(AIAnalysisReviewDecisionEntity)
            .where(
                AIAnalysisReviewDecisionEntity.analysis_source_type
                == "CANDIDATE_ASSESSMENT",
                AIAnalysisReviewDecisionEntity.source_analysis_id == assessment_id,
                AIAnalysisReviewDecisionEntity.decision.in_(
                    ["APPROVED", "APPROVED_WITH_WARNINGS"]
                ),
            )
            .order_by(AIAnalysisReviewDecisionEntity.decision_id.desc())
            .limit(1)
        )
        if decision is None:
            return _clamp_factor(0.7)
        # calibration_score 는 review entity 쪽 — decision 메타만 사용
        return _clamp_factor(1.0)

    @staticmethod
    def _citation_factor(result_body: dict[str, Any]) -> float:
        citations = result_body.get("citations") or []
        if isinstance(citations, list) and len(citations) >= 2:
            return _clamp_factor(1.0)
        if isinstance(citations, list) and len(citations) == 1:
            return _clamp_factor(0.85)
        return _clamp_factor(0.7)

    @staticmethod
    def _data_quality_factor(data_quality: str | None) -> float:
        dq = str(data_quality or "").upper()
        if dq in {"HIGH", "GOOD", "VALID"}:
            return _clamp_factor(1.0)
        if dq in {"MEDIUM", "ACCEPTABLE", "UNKNOWN"}:
            return _clamp_factor(0.85)
        if dq in {"LOW", "INSUFFICIENT"}:
            return _clamp_factor(0.6)
        if dq == "INVALID":
            return _clamp_factor(0.0)
        return _clamp_factor(0.75)

    @staticmethod
    def _independence_factor(status: str | None) -> float:
        mapping = {
            "INDEPENDENT": 1.0,
            "PARTIALLY_DEPENDENT": 0.7,
            "SAME_PROVIDER_FAMILY": 0.4,
            "DUPLICATE": 0.0,
        }
        return _clamp_factor(mapping.get(str(status or ""), 0.7))

    @staticmethod
    def _conflict_penalty(conflict_status: str | None) -> float:
        cs = str(conflict_status or "").upper()
        if cs == "MAJOR_CONFLICT":
            return _clamp_factor(0.5)
        if cs == "MINOR_CONFLICT":
            return _clamp_factor(0.85)
        if cs == "NO_CONFLICT":
            return _clamp_factor(1.0)
        return _clamp_factor(0.9)

    @staticmethod
    def preview_disclaimer() -> str:
        return REFERENCE_DISCLAIMER
