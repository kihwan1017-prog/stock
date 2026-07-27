"""STEP 11-12 — Queue → CandidateRun/Result 매핑 (금지 필드 복사 없음)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from stock_platform.ai.candidate_promotion.constants import (
    FORBIDDEN_TRADING_KEYS,
    MAPPING_VERSION,
    PROMOTION_RUN_TYPE,
    SCORE_SOURCE_TYPE,
)
from stock_platform.ai.candidate_promotion.score import compute_promotion_score
from stock_platform.ai.candidate_recommendation_queue.entities import (
    AICandidateRecommendationQueueEntity,
)


def _strip_forbidden(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if str(key).lower() in FORBIDDEN_TRADING_KEYS:
            continue
        if isinstance(value, dict):
            cleaned[key] = _strip_forbidden(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _strip_forbidden(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            cleaned[key] = value
    return cleaned


def build_score_inputs(
    queue: AICandidateRecommendationQueueEntity,
    *,
    review_overall_scores: list[float],
    warning_count: int,
    has_critical: bool,
) -> dict[str, Any]:
    return compute_promotion_score(
        review_overall_scores=review_overall_scores,
        source_quality_score=queue.source_quality_score,
        confidence=queue.confidence,
        agreement_level=queue.agreement_level,
        risk_score=queue.risk_score,
        warning_count=warning_count,
        has_critical=has_critical,
    )


def build_candidate_run_preview(
    *,
    queue: AICandidateRecommendationQueueEntity,
    promotion_request_id: int,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    trade_date = as_of_date or date.today()
    return _strip_forbidden(
        {
            "run_type": PROMOTION_RUN_TYPE,
            "exchange_code": queue.exchange_code,
            "as_of_date": trade_date.isoformat(),
            "requested_count": 1,
            "evaluated_count": 1,
            "skipped_count": 0,
            "selected_count": 1,
            "minimum_score": Decimal("0"),
            "require_all_rules": False,
            "status_code": "COMPLETED",
            "promotion_request_id": promotion_request_id,
            "queue_id": queue.queue_id,
            "mapping_version": MAPPING_VERSION,
            "market_type": queue.market_type,
            "source_type": queue.source_type,
        }
    )


def build_candidate_result_preview(
    *,
    queue: AICandidateRecommendationQueueEntity,
    promotion_request_id: int,
    score_payload: dict[str, Any],
    as_of_date: date | None = None,
) -> dict[str, Any]:
    trade_date = as_of_date or date.today()
    total_score = Decimal(str(score_payload["total_score"]))

    score_breakdown = _strip_forbidden(
        {
            "source_type": SCORE_SOURCE_TYPE,
            "trading_eligibility": False,
            "strategy_eligibility": False,
            "order_eligibility": False,
            "runtime_eligibility": False,
            "promotion_request_id": promotion_request_id,
            "queue_id": queue.queue_id,
            "mapping_version": MAPPING_VERSION,
            "formula_version": score_payload["formula_version"],
            "source_type_ref": queue.source_type,
            "source_id": queue.candidate_assessment_id
            or queue.candidate_consensus_id,
            "source_result_hash": queue.source_result_hash,
            "evidence_bundle_hash": queue.evidence_bundle_hash,
            "queue_decision": queue.queue_status,
            "score_components": score_payload.get("components"),
            "promoted_status": "PROMOTED_REVIEWED",
            "revoked": False,
        }
    )

    rule_result = _strip_forbidden(
        {
            "source": "AI_REVIEW_PROMOTION",
            "promotion_request_id": promotion_request_id,
            "queue_id": queue.queue_id,
            "source_type": queue.source_type,
            "passed_count": 0,
            "passed": False,
            "rules": [],
            "note": "AI review promotion — not screener rule pass",
        }
    )

    return {
        "rank_no": 1,
        "exchange_code": queue.exchange_code,
        "symbol": queue.symbol,
        "trade_date": trade_date.isoformat(),
        "total_score": str(total_score),
        "rules_passed_count": 0,
        "all_rules_passed": False,
        "rule_result": rule_result,
        "score_breakdown": score_breakdown,
    }


def build_commit_payloads(
    *,
    queue: AICandidateRecommendationQueueEntity,
    promotion_request_id: int,
    score_payload: dict[str, Any],
    promoted_by: str,
    as_of_date: date | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Commit용 Run/Result dict — service에서 ORM INSERT."""
    run_preview = build_candidate_run_preview(
        queue=queue,
        promotion_request_id=promotion_request_id,
        as_of_date=as_of_date,
    )
    result_preview = build_candidate_result_preview(
        queue=queue,
        promotion_request_id=promotion_request_id,
        score_payload=score_payload,
        as_of_date=as_of_date,
    )
    result_preview["promoted_by"] = promoted_by
    result_preview["promoted_at"] = datetime.now(timezone.utc).isoformat()
    return run_preview, result_preview


def candidate_result_hash(result_preview: dict[str, Any]) -> str:
    payload = json.dumps(result_preview, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:64]
