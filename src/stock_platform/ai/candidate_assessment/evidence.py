"""STEP 11-9 — Evidence Bundle (Safe Result만, Raw 본문·Candle 미포함)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_assessment.constants import (
    APPROVED_REVIEW_DECISIONS,
    CONFLICT_STATUS,
    EXCLUDED_REVIEW_DECISIONS,
    MAX_DISCLOSURE_EVIDENCE,
    MAX_EVIDENCE_AGE_DAYS_KRX,
    MAX_EVIDENCE_AGE_DAYS_UPBIT,
    MAX_NEWS_EVIDENCE,
    TEMPORAL_STATUS,
    VALID_SOURCE_STATUSES,
)
from stock_platform.ai.document_analysis.entities import AIDocumentAnalysisEntity
from stock_platform.ai.market_analysis.entities import AIMarketAnalysisEntity
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.ai.review.entities import AIAnalysisReviewDecisionEntity


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _truncate_summary(safe_result: dict[str, Any] | None, *, limit: int = 1500) -> str:
    if not safe_result:
        return ""
    body = safe_result.get("result") if isinstance(safe_result.get("result"), dict) else safe_result
    if not isinstance(body, dict):
        return str(body)[:limit]
    parts: list[str] = []
    for key in ("summary", "evidence_overview", "trend", "market_regime", "headline"):
        val = body.get(key)
        if val:
            parts.append(str(val))
    if not parts:
        parts.append(json.dumps(body, ensure_ascii=False)[:limit])
    return " | ".join(parts)[:limit]


def _extract_direction(safe_result: dict[str, Any] | None) -> str | None:
    if not safe_result:
        return None
    body = safe_result.get("result") if isinstance(safe_result.get("result"), dict) else safe_result
    if not isinstance(body, dict):
        return None
    for key in ("sentiment", "trend", "direction", "overall_sentiment"):
        val = body.get(key)
        if not val:
            continue
        text = str(val).upper()
        if any(w in text for w in ("POSITIVE", "BULL", "UP", "긍정")):
            return "POSITIVE"
        if any(w in text for w in ("NEGATIVE", "BEAR", "DOWN", "부정")):
            return "NEGATIVE"
        if any(w in text for w in ("NEUTRAL", "중립")):
            return "NEUTRAL"
    return "UNCERTAIN"


def _age_days(ref: datetime | None) -> float | None:
    if ref is None:
        return None
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    delta = _now() - ref
    return delta.total_seconds() / 86400.0


class AICandidateEvidenceService:
    """뉴스·공시·차트·시장 Safe Result 근거 번들."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _lookup_review(
        self,
        source_type: str,
        source_analysis_id: int,
    ) -> AIAnalysisReviewDecisionEntity | None:
        return self._session.scalar(
            select(AIAnalysisReviewDecisionEntity).where(
                AIAnalysisReviewDecisionEntity.analysis_source_type == source_type,
                AIAnalysisReviewDecisionEntity.source_analysis_id
                == source_analysis_id,
            )
        )

    def _doc_rows(
        self,
        *,
        document_type: str,
        exchange: str,
        symbol: str,
        limit: int,
    ) -> list[AIDocumentAnalysisEntity]:
        stmt = (
            select(AIDocumentAnalysisEntity)
            .where(
                AIDocumentAnalysisEntity.document_type == document_type,
                AIDocumentAnalysisEntity.analysis_status.in_(VALID_SOURCE_STATUSES),
                AIDocumentAnalysisEntity.analysis_status != "SUPERSEDED",
                or_(
                    AIDocumentAnalysisEntity.symbol == symbol,
                    AIDocumentAnalysisEntity.symbol.is_(None),
                ),
            )
            .order_by(AIDocumentAnalysisEntity.analyzed_at.desc().nullslast())
            .limit(limit * 3)
        )
        rows = list(self._session.scalars(stmt).all())
        filtered: list[AIDocumentAnalysisEntity] = []
        seen_keys: set[str] = set()
        for row in rows:
            if row.analysis_status == "SUPERSEDED":
                continue
            key = row.source_document_key or str(row.document_analysis_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            filtered.append(row)
            if len(filtered) >= limit:
                break
        return filtered

    def _market_row(
        self,
        *,
        analysis_type: str,
        exchange: str,
        symbol: str | None,
    ) -> AIMarketAnalysisEntity | None:
        stmt = select(AIMarketAnalysisEntity).where(
            AIMarketAnalysisEntity.analysis_type == analysis_type,
            AIMarketAnalysisEntity.exchange_code == exchange.upper(),
            AIMarketAnalysisEntity.analysis_status.in_(VALID_SOURCE_STATUSES),
            AIMarketAnalysisEntity.analysis_status != "SUPERSEDED",
        )
        if symbol and analysis_type == "SYMBOL_CHART":
            stmt = stmt.where(AIMarketAnalysisEntity.symbol == symbol)
        stmt = stmt.order_by(
            AIMarketAnalysisEntity.analyzed_at.desc().nullslast()
        ).limit(1)
        row = self._session.scalar(stmt)
        if row and row.analysis_status == "SUPERSEDED":
            return None
        return row

    def _temporal_for_item(
        self,
        *,
        analyzed_at: datetime | None,
        snapshot_at: datetime | None,
        max_age_days: float,
    ) -> str:
        ref = analyzed_at or snapshot_at
        age = _age_days(ref)
        if age is None:
            return "UNKNOWN"
        if age <= max_age_days * 0.5:
            return "ALIGNED"
        if age <= max_age_days:
            return "ACCEPTABLE"
        if age <= max_age_days * 2:
            return "STALE"
        return "CONFLICTED"

    def _build_item(
        self,
        *,
        evidence_type: str,
        source_analysis_type: str,
        source_analysis_id: int,
        document_analysis_id: int | None,
        market_analysis_id: int | None,
        safe_result: dict[str, Any] | None,
        analyzed_at: datetime | None,
        snapshot_at: datetime | None,
        source_version: str | None,
        data_quality: str | None,
        require_reviewed_evidence: bool,
        max_age_days: float,
        review_source_type: str,
    ) -> dict[str, Any]:
        review = self._lookup_review(review_source_type, source_analysis_id)
        review_decision = review.decision if review else None
        review_decision_id = review.decision_id if review else None

        excluded = False
        exclusion_reason: str | None = None

        if review_decision in EXCLUDED_REVIEW_DECISIONS:
            excluded = True
            exclusion_reason = f"REVIEW_{review_decision}"
        elif require_reviewed_evidence and review_decision not in APPROVED_REVIEW_DECISIONS:
            excluded = True
            exclusion_reason = "REVIEW_REQUIRED_NOT_APPROVED"

        temporal_status = self._temporal_for_item(
            analyzed_at=analyzed_at,
            snapshot_at=snapshot_at,
            max_age_days=max_age_days,
        )
        if temporal_status in {"STALE", "CONFLICTED"} and not excluded:
            exclusion_reason = exclusion_reason or f"TEMPORAL_{temporal_status}"

        summary = _truncate_summary(safe_result)
        direction = _extract_direction(safe_result)
        evidence_hash = hashlib.sha256(
            json.dumps(
                {
                    "type": evidence_type,
                    "id": source_analysis_id,
                    "version": source_version,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()[:64]

        return {
            "evidence_type": evidence_type,
            "source_analysis_type": source_analysis_type,
            "source_analysis_id": source_analysis_id,
            "document_analysis_id": document_analysis_id,
            "market_analysis_id": market_analysis_id,
            "review_decision_id": review_decision_id,
            "review_decision": review_decision,
            "source_version": source_version,
            "evidence_hash": evidence_hash,
            "quality_status": data_quality or "UNKNOWN",
            "direction": direction,
            "temporal_status": temporal_status,
            "summary": summary,
            "safe_result_summary": sanitize_for_log(
                {
                    "summary": summary,
                    "direction": direction,
                    "confidence": (
                        safe_result.get("confidence")
                        if isinstance(safe_result, dict)
                        else None
                    ),
                }
            ),
            "analyzed_at": analyzed_at.isoformat() if analyzed_at else None,
            "snapshot_at": snapshot_at.isoformat() if snapshot_at else None,
            "included": not excluded,
            "exclusion_reason": exclusion_reason,
        }

    def _compute_conflict(self, items: list[dict[str, Any]]) -> str:
        included = [i for i in items if i.get("included")]
        if len(included) < 2:
            return "INSUFFICIENT_EVIDENCE"
        directions = {
            str(i.get("direction") or "UNCERTAIN").upper()
            for i in included
            if i.get("direction")
        }
        directions.discard("UNCERTAIN")
        directions.discard("NEUTRAL")
        if len(directions) <= 1:
            return "NO_CONFLICT"
        if len(directions) == 2:
            return "MAJOR_CONFLICT"
        return "MINOR_CONFLICT"

    def _compute_temporal_bundle(
        self, items: list[dict[str, Any]]
    ) -> str:
        included = [i for i in items if i.get("included")]
        if not included:
            return "UNKNOWN"
        statuses = {str(i.get("temporal_status") or "UNKNOWN") for i in included}
        if "CONFLICTED" in statuses:
            return "CONFLICTED"
        if "STALE" in statuses:
            return "STALE"
        if statuses == {"ALIGNED"}:
            return "ALIGNED"
        if "UNKNOWN" in statuses and len(statuses) == 1:
            return "UNKNOWN"
        return "ACCEPTABLE"

    def _evidence_quality(
        self, items: list[dict[str, Any]], *, require_review: bool
    ) -> str:
        included = [i for i in items if i.get("included")]
        if not included:
            return "INSUFFICIENT"
        approved = sum(
            1
            for i in included
            if i.get("review_decision") in APPROVED_REVIEW_DECISIONS
        )
        if require_review and approved < len(included):
            return "LOW"
        if len(included) >= 3 and approved >= len(included) // 2:
            return "GOOD"
        if len(included) >= 1:
            return "ACCEPTABLE"
        return "LOW"

    def build_bundle(
        self,
        session: Session,
        *,
        market_type: str,
        exchange: str,
        symbol: str,
        include_news: bool = True,
        include_disclosure: bool = True,
        include_chart: bool = True,
        include_market: bool = True,
        require_reviewed_evidence: bool = False,
    ) -> dict[str, Any]:
        """Evidence Bundle — Raw 뉴스·Candle 미포함."""

        _ = session  # 호출부와 시그니처 일치
        exchange_upper = exchange.upper()
        max_age = (
            MAX_EVIDENCE_AGE_DAYS_KRX
            if exchange_upper == "KRX"
            else MAX_EVIDENCE_AGE_DAYS_UPBIT
        )

        items: list[dict[str, Any]] = []
        counts = {
            "news": 0,
            "disclosure": 0,
            "chart": 0,
            "market": 0,
            "included": 0,
            "excluded": 0,
        }

        if include_news and market_type == "STOCK":
            for row in self._doc_rows(
                document_type="NEWS",
                exchange=exchange_upper,
                symbol=symbol,
                limit=MAX_NEWS_EVIDENCE,
            ):
                item = self._build_item(
                    evidence_type="NEWS",
                    source_analysis_type="NEWS",
                    source_analysis_id=row.document_analysis_id,
                    document_analysis_id=row.document_analysis_id,
                    market_analysis_id=None,
                    safe_result=row.safe_result,
                    analyzed_at=row.analyzed_at,
                    snapshot_at=None,
                    source_version=row.source_version,
                    data_quality=row.analysis_status,
                    require_reviewed_evidence=require_reviewed_evidence,
                    max_age_days=max_age,
                    review_source_type="NEWS",
                )
                items.append(item)
                counts["news"] += 1

        if include_disclosure and market_type == "STOCK":
            for row in self._doc_rows(
                document_type="DISCLOSURE",
                exchange=exchange_upper,
                symbol=symbol,
                limit=MAX_DISCLOSURE_EVIDENCE,
            ):
                item = self._build_item(
                    evidence_type="DISCLOSURE",
                    source_analysis_type="DISCLOSURE",
                    source_analysis_id=row.document_analysis_id,
                    document_analysis_id=row.document_analysis_id,
                    market_analysis_id=None,
                    safe_result=row.safe_result,
                    analyzed_at=row.analyzed_at,
                    snapshot_at=None,
                    source_version=row.source_version,
                    data_quality=row.analysis_status,
                    require_reviewed_evidence=require_reviewed_evidence,
                    max_age_days=max_age,
                    review_source_type="DISCLOSURE",
                )
                items.append(item)
                counts["disclosure"] += 1

        if include_chart:
            chart = self._market_row(
                analysis_type="SYMBOL_CHART",
                exchange=exchange_upper,
                symbol=symbol,
            )
            if chart:
                item = self._build_item(
                    evidence_type="CHART",
                    source_analysis_type="CHART",
                    source_analysis_id=chart.market_analysis_id,
                    document_analysis_id=None,
                    market_analysis_id=chart.market_analysis_id,
                    safe_result=chart.safe_result,
                    analyzed_at=chart.analyzed_at,
                    snapshot_at=chart.snapshot_at,
                    source_version=chart.snapshot_version,
                    data_quality=chart.data_quality_status,
                    require_reviewed_evidence=require_reviewed_evidence,
                    max_age_days=max_age,
                    review_source_type="CHART",
                )
                items.append(item)
                counts["chart"] += 1

        if include_market:
            market = self._market_row(
                analysis_type="MARKET_OVERVIEW",
                exchange=exchange_upper,
                symbol=None,
            )
            if market:
                item = self._build_item(
                    evidence_type="MARKET",
                    source_analysis_type="MARKET",
                    source_analysis_id=market.market_analysis_id,
                    document_analysis_id=None,
                    market_analysis_id=market.market_analysis_id,
                    safe_result=market.safe_result,
                    analyzed_at=market.analyzed_at,
                    snapshot_at=market.snapshot_at,
                    source_version=market.snapshot_version,
                    data_quality=market.data_quality_status,
                    require_reviewed_evidence=require_reviewed_evidence,
                    max_age_days=max_age,
                    review_source_type="MARKET",
                )
                items.append(item)
                counts["market"] += 1

        counts["included"] = sum(1 for i in items if i.get("included"))
        counts["excluded"] = sum(1 for i in items if not i.get("included"))

        if require_reviewed_evidence and counts["included"] == 0 and items:
            return {
                "ok": False,
                "code": "NO_REVIEWED_EVIDENCE",
                "message": "승인된 Review Evidence 없음",
                "items": items,
                "counts": counts,
            }

        conflict_status = self._compute_conflict(items)
        if conflict_status not in CONFLICT_STATUS:
            conflict_status = "INSUFFICIENT_EVIDENCE"

        temporal_status = self._compute_temporal_bundle(items)
        evidence_quality = self._evidence_quality(
            items, require_review=require_reviewed_evidence
        )

        data_qualities = [
            str(i.get("quality_status") or "UNKNOWN")
            for i in items
            if i.get("included")
        ]
        if not data_qualities:
            data_quality = "UNKNOWN"
        elif any(q in {"INVALID", "BLOCKED"} for q in data_qualities):
            data_quality = "INVALID"
        elif any(q in {"STALE", "INCOMPLETE", "GAP_DETECTED"} for q in data_qualities):
            data_quality = "STALE"
        else:
            data_quality = "ACCEPTABLE"

        bundle_core = {
            "market_type": market_type,
            "exchange_code": exchange_upper,
            "symbol": symbol,
            "items": [
                {
                    k: v
                    for k, v in item.items()
                    if k not in {"safe_result_summary"}
                }
                for item in items
            ],
        }
        bundle_hash = hashlib.sha256(
            json.dumps(bundle_core, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:64]

        return {
            "ok": True,
            "items": items,
            "hash": bundle_hash,
            "counts": counts,
            "temporal_status": temporal_status,
            "conflict_status": conflict_status,
            "evidence_quality": evidence_quality,
            "data_quality": data_quality,
            "metadata_only": counts["included"] > 0 and all(
                not i.get("review_decision") for i in items if i.get("included")
            ),
        }
