"""STEP N5 — News Signal service (deterministic, LLM 금지).

N4 COMPLETED → TRUSTED symbols → NewsSignal rows.
Scanner / Combined Score / AI Gate / Shadow / Trading 비연동.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.common.settings import Settings, get_settings
from stock_platform.news.models import NewsArticle
from stock_platform.news.news_ai_analysis_constants import STATUS_COMPLETED
from stock_platform.news.news_ai_analysis_models import NewsAIAnalysis
from stock_platform.news.news_signal_constants import (
    SIGNAL_POLICY_VERSION,
    SIGNAL_VERSION,
)
from stock_platform.news.news_signal_models import NewsSignal
from stock_platform.news.news_signal_standardize import (
    mapping_confidence_for_symbol,
    standardize_symbol_signal,
)
from stock_platform.news.symbol_mapping_quality_constants import (
    N4_CONSUMABLE_QUALITY,
    QUALITY_POLICY_VERSION,
)


@dataclass
class NewsSignalRunStats:
    eligible_analyses: int = 0
    processed_analyses: int = 0
    signals_created: int = 0
    signals_reused: int = 0
    signals_updated: int = 0
    invalid: int = 0
    stale: int = 0
    low_confidence: int = 0
    valid: int = 0
    skipped_analyses: int = 0
    llm_calls: int = 0
    unique_symbols: list[str] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def _trusted_symbols_from_article(article: NewsArticle) -> list[str]:
    raw = article.raw_data if isinstance(article.raw_data, dict) else {}
    sm = raw.get("symbol_mapping") if isinstance(raw, dict) else {}
    if not isinstance(sm, dict):
        return []
    out: list[str] = []
    for ev in sm.get("mappings") or []:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("quality_status") or "") not in N4_CONSUMABLE_QUALITY:
            continue
        sym = str(ev.get("symbol") or "").upper()
        if sym.startswith("KRW-") and sym not in out:
            out.append(sym)
    return out


def _mapping_evidence(article: NewsArticle, symbol: str) -> dict[str, Any]:
    raw = article.raw_data if isinstance(article.raw_data, dict) else {}
    sm = raw.get("symbol_mapping") if isinstance(raw, dict) else {}
    if not isinstance(sm, dict):
        return {}
    target = symbol.upper()
    for ev in sm.get("mappings") or []:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("symbol") or "").upper() == target:
            return {
                "symbol": target,
                "quality_status": ev.get("quality_status"),
                "match_type": ev.get("match_type"),
                "mapping_confidence": ev.get("mapping_confidence"),
                "quality_reason": ev.get("quality_reason"),
            }
    return {"symbol": target, "quality_status": None}


class NewsSignalService:
    """COMPLETED N4 analysis → deterministic News Signals."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()

    def run_batch(
        self,
        *,
        limit: int = 50,
        analysis_ids: list[int] | None = None,
        force: bool = False,
    ) -> NewsSignalRunStats:
        stats = NewsSignalRunStats()
        now = datetime.now(timezone.utc)
        analyses = self._load_eligible(limit=limit, analysis_ids=analysis_ids)
        stats.eligible_analyses = len(analyses)
        seen_symbols: set[str] = set()

        for analysis in analyses:
            article = self._session.get(NewsArticle, analysis.article_id)
            if article is None:
                stats.skipped_analyses += 1
                stats.errors.append(
                    {
                        "analysis_id": analysis.analysis_id,
                        "error": "ARTICLE_NOT_FOUND",
                    }
                )
                continue
            trusted = _trusted_symbols_from_article(article)
            if not trusted:
                # TRUSTED 없으면 signal 생성 금지 (MARKET_WIDE 억지 생성 금지)
                stats.skipped_analyses += 1
                continue

            stats.processed_analyses += 1
            try:
                created, reused, updated, samples = self._standardize_analysis(
                    analysis=analysis,
                    article=article,
                    trusted=trusted,
                    now=now,
                    force=force,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "news_signal_standardize_failed",
                    analysis_id=analysis.analysis_id,
                    error=str(exc)[:200],
                )
                stats.errors.append(
                    {
                        "analysis_id": analysis.analysis_id,
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                    }
                )
                continue

            stats.signals_created += created
            stats.signals_reused += reused
            stats.signals_updated += updated
            for sample in samples:
                status = sample.get("signal_status")
                if status == "VALID":
                    stats.valid += 1
                elif status == "LOW_CONFIDENCE":
                    stats.low_confidence += 1
                elif status == "STALE":
                    stats.stale += 1
                elif status == "INVALID":
                    stats.invalid += 1
                sym = str(sample.get("symbol") or "")
                if sym:
                    seen_symbols.add(sym)
                if len(stats.samples) < 20:
                    stats.samples.append(sample)

        stats.unique_symbols = sorted(seen_symbols)
        stats.llm_calls = 0
        self._session.commit()
        return stats

    def _load_eligible(
        self,
        *,
        limit: int,
        analysis_ids: list[int] | None,
    ) -> list[NewsAIAnalysis]:
        q = select(NewsAIAnalysis).where(
            NewsAIAnalysis.status == STATUS_COMPLETED
        )
        if analysis_ids:
            q = q.where(NewsAIAnalysis.analysis_id.in_(analysis_ids))
        q = q.order_by(
            NewsAIAnalysis.analyzed_at.desc().nullslast(),
            NewsAIAnalysis.analysis_id.desc(),
        ).limit(max(1, min(int(limit), 200)))
        return list(self._session.scalars(q))

    def _standardize_analysis(
        self,
        *,
        analysis: NewsAIAnalysis,
        article: NewsArticle,
        trusted: list[str],
        now: datetime,
        force: bool,
    ) -> tuple[int, int, int, list[dict[str, Any]]]:
        trusted_set = {s.upper() for s in trusted}
        affected = analysis.affected_symbols or []
        if not isinstance(affected, list):
            affected = []

        # affected_symbols ∩ TRUSTED — 없으면 TRUSTED + article-level direction
        items_by_symbol: dict[str, dict[str, Any] | None] = {}
        for item in affected:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "").upper()
            if sym not in trusted_set:
                continue
            items_by_symbol[sym] = item
        if not items_by_symbol:
            for sym in trusted:
                items_by_symbol[sym] = None

        created = reused = updated = 0
        samples: list[dict[str, Any]] = []
        ai_conf = float(analysis.news_ai_confidence or 0)
        risk_flags = [
            str(f)
            for f in (analysis.risk_flags or [])
            if str(f or "").strip()
        ]

        for sym, item in items_by_symbol.items():
            map_conf = mapping_confidence_for_symbol(
                article.raw_data if isinstance(article.raw_data, dict) else {},
                sym,
            )
            evidence = _mapping_evidence(article, sym)
            payload = standardize_symbol_signal(
                article_id=int(article.article_id),
                news_analysis_id=int(analysis.analysis_id),
                symbol=sym,
                event_type=str(analysis.event_type or "OTHER"),
                sentiment=str(analysis.sentiment or "UNKNOWN"),
                news_impact_level=str(analysis.news_impact_level or "LOW"),
                time_horizon=str(analysis.time_horizon or "UNKNOWN"),
                market_scope=analysis.market_scope,
                news_ai_confidence=ai_conf,
                mapping_confidence=map_conf,
                risk_flags=risk_flags,
                affected_item=item,
                published_at=article.published_at,
                analyzed_at=analysis.analyzed_at,
                now=now,
                provenance={
                    "article_id": article.article_id,
                    "source_code": article.source_code,
                    "news_analysis_id": analysis.analysis_id,
                    "analysis_version": analysis.analysis_version,
                    "prompt_version": analysis.prompt_version,
                    "provider": analysis.provider,
                    "model": analysis.model_name,
                    "mapping_evidence": evidence,
                    "mapping_quality": evidence.get("quality_status"),
                    "quality_policy_version": QUALITY_POLICY_VERSION,
                    "signal_policy_version": SIGNAL_POLICY_VERSION,
                    "input_hash": analysis.input_hash,
                },
            )
            row, action = self._upsert_signal(payload, force=force)
            if action == "created":
                created += 1
            elif action == "reused":
                reused += 1
            else:
                updated += 1
            samples.append(self._to_sample(row, article))

        return created, reused, updated, samples

    def _upsert_signal(
        self,
        payload: dict[str, Any],
        *,
        force: bool,
    ) -> tuple[NewsSignal, str]:
        existing = self._session.scalar(
            select(NewsSignal).where(
                NewsSignal.news_ai_analysis_id
                == int(payload["news_analysis_id"]),
                NewsSignal.symbol == str(payload["symbol"]),
                NewsSignal.signal_version == SIGNAL_VERSION,
            )
        )
        if existing is not None and not force:
            return existing, "reused"

        now = datetime.now(timezone.utc)
        if existing is None:
            row = NewsSignal(
                article_id=int(payload["article_id"]),
                news_ai_analysis_id=int(payload["news_analysis_id"]),
                symbol=str(payload["symbol"]),
                signal_version=SIGNAL_VERSION,
                signal_policy_version=SIGNAL_POLICY_VERSION,
                direction=payload["direction"],
                strength=payload["strength"],
                reliability=payload["reliability"],
                signal_status=payload["signal_status"],
                event_type=payload["event_type"],
                news_impact_level=payload["news_impact_level"],
                time_horizon=payload["time_horizon"],
                news_ai_confidence=Decimal(str(payload["news_ai_confidence"])),
                mapping_confidence=Decimal(str(payload["mapping_confidence"])),
                risk_flags=payload["risk_flags"],
                reason_codes=payload["reason_codes"],
                provenance=payload["provenance"],
                published_at=payload.get("published_at"),
                analyzed_at=payload.get("analyzed_at"),
                signal_at=payload["signal_at"],
                expires_at=payload["expires_at"],
            )
            self._session.add(row)
            self._session.flush()
            return row, "created"

        existing.direction = payload["direction"]
        existing.strength = payload["strength"]
        existing.reliability = payload["reliability"]
        existing.signal_status = payload["signal_status"]
        existing.event_type = payload["event_type"]
        existing.news_impact_level = payload["news_impact_level"]
        existing.time_horizon = payload["time_horizon"]
        existing.news_ai_confidence = Decimal(
            str(payload["news_ai_confidence"])
        )
        existing.mapping_confidence = Decimal(
            str(payload["mapping_confidence"])
        )
        existing.risk_flags = payload["risk_flags"]
        existing.reason_codes = payload["reason_codes"]
        existing.provenance = payload["provenance"]
        existing.published_at = payload.get("published_at")
        existing.analyzed_at = payload.get("analyzed_at")
        existing.signal_at = payload["signal_at"]
        existing.expires_at = payload["expires_at"]
        existing.updated_at = now
        self._session.flush()
        return existing, "updated"

    @staticmethod
    def _to_sample(row: NewsSignal, article: NewsArticle) -> dict[str, Any]:
        return {
            "signal_id": row.signal_id,
            "article_id": row.article_id,
            "news_analysis_id": row.news_ai_analysis_id,
            "source_type": article.source_code,
            "title": article.title,
            "symbol": row.symbol,
            "direction": row.direction,
            "strength": row.strength,
            "reliability": row.reliability,
            "signal_status": row.signal_status,
            "event_type": row.event_type,
            "news_impact_level": row.news_impact_level,
            "time_horizon": row.time_horizon,
            "news_ai_confidence": float(row.news_ai_confidence),
            "mapping_confidence": float(row.mapping_confidence),
            "risk_flags": row.risk_flags,
            "reason_codes": row.reason_codes,
            "expires_at": (
                row.expires_at.isoformat() if row.expires_at else None
            ),
            "informational_only": True,
            "not_a_trade_recommendation": True,
        }


def list_recent_signals(session: Session, *, limit: int = 20) -> list[dict]:
    rows = session.execute(
        select(NewsSignal, NewsArticle)
        .join(
            NewsArticle,
            NewsArticle.article_id == NewsSignal.article_id,
        )
        .order_by(NewsSignal.created_at.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return [NewsSignalService._to_sample(sig, art) for sig, art in rows]


def signal_stats_snapshot(session: Session) -> dict[str, Any]:
    total = session.scalar(select(func.count()).select_from(NewsSignal)) or 0

    def _group(col):
        rows = session.execute(
            select(col, func.count()).group_by(col)
        ).all()
        return {str(k): int(v) for k, v in rows if k is not None}

    by_symbol = session.execute(
        select(NewsSignal.symbol, func.count())
        .group_by(NewsSignal.symbol)
        .order_by(func.count().desc())
        .limit(30)
    ).all()

    completed_n4 = session.scalar(
        select(func.count()).select_from(NewsAIAnalysis).where(
            NewsAIAnalysis.status == STATUS_COMPLETED
        )
    ) or 0

    settings = get_settings()
    return {
        "informational_only": True,
        "trade_recommendation": False,
        "scanner_apply": False,
        "combined_score": False,
        "ai_gate": False,
        "llm_calls": 0,
        "signal_version": SIGNAL_VERSION,
        "signal_policy_version": SIGNAL_POLICY_VERSION,
        "enabled": bool(
            getattr(settings, "upbit_news_signal_enabled", False)
        ),
        "interval_seconds": float(
            getattr(settings, "upbit_news_signal_interval_seconds", 300)
        ),
        "total_signals": int(total),
        "n4_completed_analyses": int(completed_n4),
        "by_direction": _group(NewsSignal.direction),
        "by_strength": _group(NewsSignal.strength),
        "by_reliability": _group(NewsSignal.reliability),
        "by_status": _group(NewsSignal.signal_status),
        "by_event_type": _group(NewsSignal.event_type),
        "by_symbol": [
            {"symbol": s, "count": int(c)} for s, c in by_symbol
        ],
        "contract": {
            "positive_neq_buy": True,
            "negative_neq_sell": True,
            "news_signal_neq_ai_gate": True,
        },
    }


def signal_status_snapshot(session: Session) -> dict[str, Any]:
    return signal_stats_snapshot(session)
