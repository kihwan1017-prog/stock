"""STEP 11-12 — Promotion eligibility (Candidate INSERT 0).

is_expired는 keyword-only 인자(expires_at=)로만 호출한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_promotion.constants import (
    ELIGIBILITY_VERSION,
    PROMOTABLE_QUEUE_STATUSES,
    REFERENCE_DISCLAIMER,
    SOURCE_TYPES,
)
from stock_platform.ai.candidate_recommendation_queue.entities import (
    AICandidateRecommendationDecisionEntity,
    AICandidateRecommendationFindingEntity,
    AICandidateRecommendationQueueEntity,
    AICandidateRecommendationReviewEntity,
)
from stock_platform.ai.candidate_recommendation_queue.expiration import is_expired
from stock_platform.ai.candidate_recommendation_queue.staleness import (
    AIRecommendationQueueStalenessService,
)
from stock_platform.markets.models import Instrument


class AICandidatePromotionEligibilityService:
    """
    Queue → Promotion 적격성 검증.

    Safety: strategy.candidate INSERT 금지, trading/order/runtime import 금지.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._staleness = AIRecommendationQueueStalenessService(session)

    def validate_queue(
        self,
        queue: AICandidateRecommendationQueueEntity,
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        blockers: list[str] = []
        warnings: list[str] = []

        if queue.queue_status not in PROMOTABLE_QUEUE_STATUSES:
            blockers.append(f"QUEUE_STATUS_{queue.queue_status}")
            checks.append(
                self._check(
                    "QUEUE",
                    "QUEUE_STATUS",
                    "FAIL",
                    "CRITICAL",
                    f"status {queue.queue_status} not promotable",
                )
            )

        latest_decision = self._latest_decision(queue.queue_id)
        if latest_decision not in PROMOTABLE_QUEUE_STATUSES:
            blockers.append(f"DECISION_{latest_decision or 'NONE'}")
            checks.append(
                self._check(
                    "QUEUE",
                    "QUEUE_DECISION",
                    "FAIL",
                    "CRITICAL",
                    f"decision {latest_decision} invalid",
                )
            )

        if is_expired(expires_at=queue.expires_at):
            blockers.append("QUEUE_EXPIRED")
            checks.append(
                self._check(
                    "EXPIRATION",
                    "QUEUE_EXPIRED",
                    "FAIL",
                    "CRITICAL",
                    "queue expired",
                )
            )

        if queue.source_type not in SOURCE_TYPES:
            blockers.append("INVALID_SOURCE_TYPE")
            checks.append(
                self._check(
                    "SOURCE",
                    "SOURCE_TYPE",
                    "FAIL",
                    "CRITICAL",
                    queue.source_type,
                )
            )

        stale = self._staleness.check(
            source_type=queue.source_type,
            candidate_assessment_id=queue.candidate_assessment_id,
            candidate_consensus_id=queue.candidate_consensus_id,
            stored_source_result_hash=queue.source_result_hash,
            stored_evidence_bundle_hash=queue.evidence_bundle_hash,
        )
        if stale.get("stale"):
            blockers.extend(stale.get("reasons") or ["SOURCE_STALE"])
            checks.append(
                self._check(
                    "SOURCE",
                    "SOURCE_STALE",
                    "FAIL",
                    "CRITICAL",
                    ",".join(stale.get("reasons") or []),
                )
            )

        critical_count, unresolved_high = self._finding_counts(queue.queue_id)
        if critical_count > 0:
            blockers.append("CRITICAL_FINDINGS")
            checks.append(
                self._check(
                    "FINDING",
                    "CRITICAL_FINDINGS",
                    "FAIL",
                    "CRITICAL",
                    f"{critical_count} critical findings",
                )
            )
        if (
            unresolved_high > 0
            and queue.queue_status == "APPROVED_FOR_CONSIDERATION"
        ):
            blockers.append("UNRESOLVED_HIGH_FINDINGS")
            checks.append(
                self._check(
                    "FINDING",
                    "UNRESOLVED_HIGH",
                    "FAIL",
                    "HIGH",
                    f"{unresolved_high} unresolved HIGH findings",
                )
            )

        instrument_check = self._validate_instrument(queue)
        checks.extend(instrument_check["checks"])
        blockers.extend(instrument_check["blockers"])
        warnings.extend(instrument_check["warnings"])

        if queue.queue_status == "APPROVED_WITH_WARNINGS":
            warnings.append("QUEUE_APPROVED_WITH_WARNINGS")

        snapshot = {
            "queue_id": queue.queue_id,
            "queue_status": queue.queue_status,
            "queue_version": queue.lock_version,
            "latest_decision": latest_decision,
            "source_type": queue.source_type,
            "source_id": queue.candidate_assessment_id
            or queue.candidate_consensus_id,
            "source_result_hash": queue.source_result_hash,
            "evidence_bundle_hash": queue.evidence_bundle_hash,
            "critical_findings_count": critical_count,
            "unresolved_high_findings_count": unresolved_high,
            "eligibility_version": ELIGIBILITY_VERSION,
        }

        return {
            "allowed": len(blockers) == 0,
            "blockers": blockers,
            "warnings": warnings,
            "checks": checks,
            "snapshot": snapshot,
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def _validate_instrument(
        self, queue: AICandidateRecommendationQueueEntity
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        blockers: list[str] = []
        warnings: list[str] = []

        instrument: Instrument | None = None
        if queue.instrument_id is not None:
            instrument = self._session.get(Instrument, queue.instrument_id)
        if instrument is None:
            instrument = self._session.scalar(
                select(Instrument).where(
                    Instrument.exchange_code == queue.exchange_code,
                    Instrument.symbol == queue.symbol,
                )
            )

        if instrument is None:
            blockers.append("INSTRUMENT_NOT_FOUND")
            checks.append(
                self._check(
                    "INSTRUMENT",
                    "INSTRUMENT_MISSING",
                    "FAIL",
                    "CRITICAL",
                    f"{queue.exchange_code}:{queue.symbol}",
                )
            )
            return {"checks": checks, "blockers": blockers, "warnings": warnings}

        if instrument.symbol != queue.symbol:
            blockers.append("SYMBOL_MISMATCH")
            checks.append(
                self._check(
                    "INSTRUMENT",
                    "SYMBOL_MISMATCH",
                    "FAIL",
                    "CRITICAL",
                    instrument.symbol,
                )
            )

        if not instrument.is_active:
            blockers.append("INSTRUMENT_INACTIVE")
            checks.append(
                self._check(
                    "INSTRUMENT",
                    "INSTRUMENT_INACTIVE",
                    "FAIL",
                    "CRITICAL",
                    "inactive instrument",
                )
            )

        if instrument.delisted_date is not None:
            blockers.append("INSTRUMENT_DELISTED")
            checks.append(
                self._check(
                    "INSTRUMENT",
                    "INSTRUMENT_DELISTED",
                    "FAIL",
                    "CRITICAL",
                    instrument.delisted_date.isoformat(),
                )
            )

        extra = instrument.extra_data or {}
        halt_flags = [
            k
            for k, v in extra.items()
            if str(k).lower()
            in {"halted", "trading_halt", "suspended", "delisted"}
            and bool(v)
        ]
        if halt_flags:
            blockers.append("INSTRUMENT_TRADING_HALT")
            checks.append(
                self._check(
                    "INSTRUMENT",
                    "TRADING_HALT",
                    "FAIL",
                    "CRITICAL",
                    ",".join(halt_flags),
                )
            )

        checks.append(
            self._check(
                "INSTRUMENT",
                "INSTRUMENT_OK",
                "PASS",
                "INFO",
                f"instrument_id={instrument.instrument_id}",
            )
        )
        return {"checks": checks, "blockers": blockers, "warnings": warnings}

    def _latest_decision(self, queue_id: int) -> str | None:
        return self._session.scalar(
            select(AICandidateRecommendationDecisionEntity.decision)
            .where(AICandidateRecommendationDecisionEntity.queue_id == queue_id)
            .order_by(
                AICandidateRecommendationDecisionEntity.decision_version.desc()
            )
            .limit(1)
        )

    def _finding_counts(self, queue_id: int) -> tuple[int, int]:
        review_ids = list(
            self._session.scalars(
                select(AICandidateRecommendationReviewEntity.review_id).where(
                    AICandidateRecommendationReviewEntity.queue_id == queue_id,
                    AICandidateRecommendationReviewEntity.review_status
                    == "SUBMITTED",
                )
            )
        )
        if not review_ids:
            return 0, 0
        findings = list(
            self._session.scalars(
                select(AICandidateRecommendationFindingEntity).where(
                    AICandidateRecommendationFindingEntity.review_id.in_(
                        review_ids
                    )
                )
            )
        )
        critical = sum(1 for f in findings if f.severity == "CRITICAL")
        unresolved_high = sum(
            1
            for f in findings
            if f.severity == "HIGH"
            and f.resolution_status
            not in {"RESOLVED", "DISMISSED", "ACKNOWLEDGED"}
        )
        return critical, unresolved_high

    @staticmethod
    def _check(
        validation_type: str,
        check_code: str,
        status: str,
        severity: str,
        message: str,
    ) -> dict[str, Any]:
        return {
            "validation_type": validation_type,
            "check_code": check_code,
            "validation_status": status,
            "severity": severity,
            "message_sanitized": message[:2000],
        }

    @staticmethod
    def side_effect_guard_summary() -> dict[str, Any]:
        """Dry-run/Commit 전 Side Effect 0 선언."""
        return {
            "strategy_create": 0,
            "risk_change": 0,
            "order_create": 0,
            "broker_call": 0,
            "runtime_change": 0,
            "scheduler_change": 0,
            "candidate_insert": 0,
            "signal_create": 0,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
