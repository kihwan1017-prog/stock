"""STEP N4 — UPBIT AI News Analysis orchestrator (INFORMATIONAL ONLY).

Scanner / Shadow / AI Gate / Trading 경로와 완전 분리.
1 Article = 최대 1 AI Call. concurrency = 1.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.document_analysis.injection_guard import (
    inspect_document_injection,
    wrap_untrusted,
)
from stock_platform.ai.document_analysis.sanitizer import sanitize_document_text
from stock_platform.ai.ollama_client import OllamaClient, OllamaError
from stock_platform.common.logger import logger
from stock_platform.common.settings import Settings, get_settings
from stock_platform.news.collector_constants import (
    SOURCE_CODE_CRYPTO_NEWS,
    SOURCE_CODE_UPBIT_NOTICE,
)
from stock_platform.news.models import NewsArticle
from stock_platform.news.news_ai_analysis_constants import (
    ANALYSIS_VERSION,
    MAX_BODY_CHARS,
    NEWS_AI_ANALYSIS_SCHEMA,
    PROMPT_VERSION,
    PROVIDER_OLLAMA,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    SYSTEM_PROMPT,
)
from stock_platform.news.news_ai_analysis_models import NewsAIAnalysis
from stock_platform.news.news_ai_analysis_validate import (
    NewsAIValidationError,
    validate_and_normalize_result,
)
from stock_platform.news.symbol_mapping_quality_constants import (
    N4_CONSUMABLE_QUALITY,
    QUALITY_TRUSTED,
)


_ANALYZE_LOCK = asyncio.Lock()


@dataclass
class NewsAIRunStats:
    scanned: int = 0
    analyzed: int = 0
    reused: int = 0
    skipped: int = 0
    failed: int = 0
    ai_calls: int = 0
    elapsed_ms_total: int = 0
    elapsed_ms_max: int = 0
    samples: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def extract_trusted_symbols(article: NewsArticle) -> list[str]:
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
    # fallback: n4_consumable_symbols
    for sym in sm.get("n4_consumable_symbols") or []:
        s = str(sym).upper()
        if s.startswith("KRW-") and s not in out:
            out.append(s)
    return out


def build_input_hash(
    *,
    content_hash: str,
    trusted_symbols: list[str],
    analysis_version: str,
    prompt_version: str,
    model: str,
) -> str:
    payload = "|".join(
        [
            content_hash,
            analysis_version,
            prompt_version,
            model,
            ",".join(sorted(trusted_symbols)),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class NewsAIAnalysisService:
    """Article → TRUSTED symbols → Ollama structured analysis → store."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        ollama: OllamaClient | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._ollama = ollama
        self._owns_ollama = ollama is None

    async def aclose(self) -> None:
        if self._owns_ollama and self._ollama is not None:
            await self._ollama.aclose()

    def _get_ollama(self) -> OllamaClient:
        if self._ollama is None:
            model = getattr(
                self._settings,
                "upbit_news_ai_analysis_model",
                None,
            ) or self._settings.ollama_model
            timeout = float(
                getattr(
                    self._settings,
                    "upbit_news_ai_analysis_timeout_seconds",
                    self._settings.ollama_timeout_seconds,
                )
            )
            self._ollama = OllamaClient(
                settings=self._settings,
                model=model,
                timeout_seconds=timeout,
            )
        return self._ollama

    def find_completed(
        self,
        *,
        article_id: int,
        input_hash: str,
        model: str,
    ) -> NewsAIAnalysis | None:
        return self._session.scalar(
            select(NewsAIAnalysis).where(
                NewsAIAnalysis.article_id == article_id,
                NewsAIAnalysis.analysis_version == ANALYSIS_VERSION,
                NewsAIAnalysis.model_name == model,
                NewsAIAnalysis.prompt_version == PROMPT_VERSION,
                NewsAIAnalysis.input_hash == input_hash,
                NewsAIAnalysis.status == STATUS_COMPLETED,
            )
        )

    async def analyze_article(
        self,
        article: NewsArticle,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """1 article = 최대 1 AI call (lock으로 concurrency 1)."""

        async with _ANALYZE_LOCK:
            return await self._analyze_unlocked(article, force=force)

    async def _analyze_unlocked(
        self,
        article: NewsArticle,
        *,
        force: bool,
    ) -> dict[str, Any]:
        trusted = extract_trusted_symbols(article)
        model = self._get_ollama().model
        input_hash = build_input_hash(
            content_hash=str(article.content_hash),
            trusted_symbols=trusted,
            analysis_version=ANALYSIS_VERSION,
            prompt_version=PROMPT_VERSION,
            model=model,
        )

        if not trusted:
            row = self._save_row(
                article=article,
                model=model,
                input_hash=input_hash,
                status=STATUS_SKIPPED,
                trusted=trusted,
                error_code="NO_TRUSTED_SYMBOL",
                error_message="no TRUSTED symbol mapping",
            )
            return {"status": STATUS_SKIPPED, "analysis_id": row.analysis_id, "ai_call": False}

        if not force:
            existing = self.find_completed(
                article_id=int(article.article_id),
                input_hash=input_hash,
                model=model,
            )
            if existing is not None:
                return {
                    "status": STATUS_COMPLETED,
                    "analysis_id": existing.analysis_id,
                    "ai_call": False,
                    "reused": True,
                    "sample": self._to_sample(existing, article),
                }

        title = article.title or ""
        body_raw = self._extract_body(article)
        truncated = False
        if len(body_raw) > MAX_BODY_CHARS:
            body_raw = body_raw[:MAX_BODY_CHARS]
            truncated = True

        sanitized = sanitize_document_text(body_raw, kind="news")
        body = str(sanitized.get("normalized_body") or body_raw)
        injection = inspect_document_injection(f"{title}\n{body}")
        wrapped = wrap_untrusted("NEWS", body)

        raw_meta = article.raw_data if isinstance(article.raw_data, dict) else {}
        user_prompt = self._build_user_prompt(
            article=article,
            title=title,
            wrapped_body=wrapped,
            trusted=trusted,
            truncated=truncated,
            injection_warnings=list(injection.get("warnings") or [])[:5],
            category=str(raw_meta.get("category") or ""),
        )

        started = time.perf_counter()
        try:
            raw = await self._get_ollama().chat_structured(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                response_schema=NEWS_AI_ANALYSIS_SCHEMA,
            )
            normalized = validate_and_normalize_result(
                raw, trusted_symbols=trusted
            )
            elapsed = int((time.perf_counter() - started) * 1000)
            row = self._save_row(
                article=article,
                model=model,
                input_hash=input_hash,
                status=STATUS_COMPLETED,
                trusted=trusted,
                truncated=truncated,
                elapsed_ms=elapsed,
                payload=normalized,
                raw_result=raw if isinstance(raw, dict) else {},
            )
            return {
                "status": STATUS_COMPLETED,
                "analysis_id": row.analysis_id,
                "ai_call": True,
                "elapsed_ms": elapsed,
                "sample": self._to_sample(row, article),
            }
        except (OllamaError, NewsAIValidationError, TimeoutError) as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            code = getattr(exc, "code", type(exc).__name__)
            row = self._save_row(
                article=article,
                model=model,
                input_hash=input_hash,
                status=STATUS_FAILED,
                trusted=trusted,
                truncated=truncated,
                elapsed_ms=elapsed,
                error_code=str(code)[:80],
                error_message=str(exc)[:2000],
            )
            logger.warning(
                "news_ai_analysis_failed",
                article_id=article.article_id,
                error=str(exc)[:200],
            )
            return {
                "status": STATUS_FAILED,
                "analysis_id": row.analysis_id,
                "ai_call": True,
                "elapsed_ms": elapsed,
                "error_code": str(code),
                "error_message": str(exc)[:300],
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.perf_counter() - started) * 1000)
            row = self._save_row(
                article=article,
                model=model,
                input_hash=input_hash,
                status=STATUS_FAILED,
                trusted=trusted,
                truncated=truncated,
                elapsed_ms=elapsed,
                error_code="UNEXPECTED",
                error_message=f"{type(exc).__name__}: {exc}"[:2000],
            )
            return {
                "status": STATUS_FAILED,
                "analysis_id": row.analysis_id,
                "ai_call": True,
                "elapsed_ms": elapsed,
                "error_code": "UNEXPECTED",
            }

    async def run_batch(
        self,
        *,
        limit: int = 5,
        article_ids: list[int] | None = None,
        force: bool = False,
    ) -> NewsAIRunStats:
        batch = max(1, min(int(limit), 5))
        stats = NewsAIRunStats()
        if article_ids:
            articles = list(
                self._session.scalars(
                    select(NewsArticle).where(
                        NewsArticle.article_id.in_(article_ids)
                    )
                )
            )
            articles = articles[:batch]
        else:
            # N9: fresh TRUSTED + 미처리 우선 (이미 COMPLETED/FAILED 재조회 금지)
            articles = self._list_fresh_unprocessed_trusted(limit=batch)

        completed_analysis_ids: list[int] = []
        for article in articles:
            stats.scanned += 1
            out = await self.analyze_article(article, force=force)
            status = out.get("status")
            if status == STATUS_COMPLETED:
                if out.get("reused"):
                    stats.reused += 1
                else:
                    stats.analyzed += 1
                if out.get("ai_call"):
                    stats.ai_calls += 1
                sample = out.get("sample")
                if sample and len(stats.samples) < 10:
                    stats.samples.append(sample)
                analysis_id = out.get("analysis_id")
                if analysis_id is not None:
                    completed_analysis_ids.append(int(analysis_id))
                    # 건별 commit 후 N5 — 별도 session이 N4 row를 보게 함
                    try:
                        self._session.commit()
                    except Exception as commit_exc:  # noqa: BLE001
                        logger.warning(
                            "news_n4_mid_batch_commit_failed",
                            error=str(commit_exc)[:200],
                        )
                        self._session.rollback()
                    else:
                        self._trigger_n5_fail_isolated([int(analysis_id)])
            elif status == STATUS_SKIPPED:
                stats.skipped += 1
            else:
                stats.failed += 1
                stats.errors.append(
                    {
                        "article_id": article.article_id,
                        "error_code": out.get("error_code"),
                        "error_message": out.get("error_message"),
                    }
                )
                if out.get("ai_call"):
                    stats.ai_calls += 1
            elapsed = int(out.get("elapsed_ms") or 0)
            stats.elapsed_ms_total += elapsed
            stats.elapsed_ms_max = max(stats.elapsed_ms_max, elapsed)

        self._session.commit()
        if completed_analysis_ids:
            logger.info(
                "news_n4_to_n5_event_trigger",
                analysis_ids=completed_analysis_ids,
                mode="per_article_fail_isolated",
            )
        return stats

    def _list_fresh_unprocessed_trusted(self, *, limit: int) -> list[NewsArticle]:
        """created_at 최신 우선 · TRUSTED · analysis row 없는 article만."""

        candidates = list(
            self._session.scalars(
                select(NewsArticle)
                .where(
                    NewsArticle.source_code.in_(
                        [SOURCE_CODE_UPBIT_NOTICE, SOURCE_CODE_CRYPTO_NEWS]
                    )
                )
                .order_by(
                    NewsArticle.created_at.desc().nullslast(),
                    NewsArticle.article_id.desc(),
                )
                .limit(500)
            )
        )
        selected: list[NewsArticle] = []
        for article in candidates:
            if not extract_trusted_symbols(article):
                continue
            # 기존 FAILED/COMPLETED/SKIPPED 재분석 금지 — row 있으면 skip
            existing_id = self._session.scalar(
                select(NewsAIAnalysis.analysis_id)
                .where(NewsAIAnalysis.article_id == int(article.article_id))
                .limit(1)
            )
            if existing_id is not None:
                continue
            selected.append(article)
            if len(selected) >= limit:
                break
        return selected

    def _trigger_n5_fail_isolated(
        self, analysis_ids: list[int]
    ) -> dict[str, Any]:
        """N5 실패가 N4 성공을 뒤집지 않음. 별도 session + LLM=0."""

        if not analysis_ids:
            return {"skipped": True, "reason": "NO_IDS"}
        if not bool(
            getattr(self._settings, "upbit_news_signal_enabled", False)
        ):
            return {"skipped": True, "reason": "N5_DISABLED"}

        from dataclasses import asdict

        from stock_platform.database.session import get_session_factory
        from stock_platform.news.news_signal_service import NewsSignalService

        session = None
        try:
            session = get_session_factory()()
            service = NewsSignalService(session)
            stats = service.run_batch(
                limit=max(1, len(analysis_ids)),
                analysis_ids=analysis_ids,
                force=False,
            )
            return {"ok": True, "stats": asdict(stats), "llm_calls": 0}
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "news_n5_event_trigger_failed",
                analysis_ids=analysis_ids,
                error=str(exc)[:300],
            )
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }
        finally:
            if session is not None:
                session.close()

    def _save_row(
        self,
        *,
        article: NewsArticle,
        model: str,
        input_hash: str,
        status: str,
        trusted: list[str],
        truncated: bool = False,
        elapsed_ms: int | None = None,
        payload: dict[str, Any] | None = None,
        raw_result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> NewsAIAnalysis:
        # 동일 idempotency key 가 있으면 update
        existing = self._session.scalar(
            select(NewsAIAnalysis).where(
                NewsAIAnalysis.article_id == int(article.article_id),
                NewsAIAnalysis.analysis_version == ANALYSIS_VERSION,
                NewsAIAnalysis.model_name == model,
                NewsAIAnalysis.prompt_version == PROMPT_VERSION,
                NewsAIAnalysis.input_hash == input_hash,
            )
        )
        now = datetime.now(timezone.utc)
        payload = payload or {}
        if existing is None:
            existing = NewsAIAnalysis(
                article_id=int(article.article_id),
                analysis_version=ANALYSIS_VERSION,
                provider=PROVIDER_OLLAMA,
                model_name=model,
                prompt_version=PROMPT_VERSION,
                status=status,
                input_hash=input_hash,
                trusted_symbols_input=trusted,
            )
            self._session.add(existing)

        existing.status = status
        existing.truncated = truncated
        existing.trusted_symbols_input = trusted
        existing.error_code = error_code
        existing.error_message = error_message
        existing.elapsed_ms = elapsed_ms
        existing.raw_result = raw_result or {}
        if status == STATUS_COMPLETED:
            existing.event_type = payload.get("event_type")
            existing.sentiment = payload.get("sentiment")
            existing.news_impact_level = payload.get("news_impact_level")
            existing.time_horizon = payload.get("time_horizon")
            existing.market_scope = payload.get("market_scope")
            existing.summary = payload.get("summary")
            existing.reasoning_summary = payload.get("reasoning_summary")
            conf = payload.get("news_ai_confidence")
            existing.news_ai_confidence = (
                Decimal(str(conf)) if conf is not None else None
            )
            existing.affected_symbols = payload.get("affected_symbols") or []
            existing.risk_flags = payload.get("risk_flags") or []
            existing.analyzed_at = now
            existing.error_code = None
            existing.error_message = None
        self._session.flush()
        return existing

    @staticmethod
    def _extract_body(article: NewsArticle) -> str:
        parts: list[str] = []
        if article.description:
            parts.append(str(article.description))
        raw = article.raw_data if isinstance(article.raw_data, dict) else {}
        for key in ("normalized_text", "body", "content"):
            if raw.get(key):
                parts.append(str(raw[key]))
        return "\n".join(parts)

    @staticmethod
    def _build_user_prompt(
        *,
        article: NewsArticle,
        title: str,
        wrapped_body: str,
        trusted: list[str],
        truncated: bool,
        injection_warnings: list[str],
        category: str,
    ) -> str:
        return (
            f"source_type: {article.source_code}\n"
            f"category_hint: {category or 'UNKNOWN'}\n"
            f"published_at: {article.published_at.isoformat() if article.published_at else ''}\n"
            f"trusted_symbols: {json.dumps(trusted, ensure_ascii=False)}\n"
            f"truncated: {truncated}\n"
            f"injection_warnings: {json.dumps(injection_warnings, ensure_ascii=False)}\n"
            f"title: {title}\n"
            f"body:\n{wrapped_body}\n"
        )

    @staticmethod
    def _to_sample(row: NewsAIAnalysis, article: NewsArticle) -> dict[str, Any]:
        return {
            "analysis_id": row.analysis_id,
            "article_id": row.article_id,
            "source_type": article.source_code,
            "title": article.title,
            "trusted_symbols": row.trusted_symbols_input,
            "event_type": row.event_type,
            "sentiment": row.sentiment,
            "news_impact_level": row.news_impact_level,
            "time_horizon": row.time_horizon,
            "news_ai_confidence": (
                float(row.news_ai_confidence)
                if row.news_ai_confidence is not None
                else None
            ),
            "affected_symbols": row.affected_symbols,
            "risk_flags": row.risk_flags,
            "elapsed_ms": row.elapsed_ms,
            "status": row.status,
            "informational_only": True,
            "not_a_trade_recommendation": True,
        }


def list_recent_analyses(
    session: Session, *, limit: int = 20
) -> list[dict[str, Any]]:
    rows = list(
        session.execute(
            select(NewsAIAnalysis, NewsArticle)
            .join(
                NewsArticle,
                NewsArticle.article_id == NewsAIAnalysis.article_id,
            )
            .order_by(NewsAIAnalysis.created_at.desc())
            .limit(limit)
        ).all()
    )
    out: list[dict[str, Any]] = []
    for analysis, article in rows:
        out.append(NewsAIAnalysisService._to_sample(analysis, article))
    return out


def analysis_status_snapshot(session: Session) -> dict[str, Any]:
    settings = get_settings()
    from sqlalchemy import func

    counts = dict(
        session.execute(
            select(NewsAIAnalysis.status, func.count())
            .group_by(NewsAIAnalysis.status)
        ).all()
    )
    return {
        "enabled": bool(
            getattr(settings, "upbit_news_ai_analysis_enabled", False)
        ),
        "interval_seconds": int(
            getattr(
                settings, "upbit_news_ai_analysis_interval_seconds", 900
            )
        ),
        "batch_size": int(
            getattr(settings, "upbit_news_ai_analysis_batch_size", 5)
        ),
        "model": getattr(settings, "upbit_news_ai_analysis_model", None)
        or settings.ollama_model,
        "analysis_version": ANALYSIS_VERSION,
        "prompt_version": PROMPT_VERSION,
        "max_concurrency": 1,
        "informational_only": True,
        "consumes_quality": QUALITY_TRUSTED,
        "n4_contract": "TRUSTED_MAPPING_ONLY",
        "status_counts": {str(k): int(v) for k, v in counts.items()},
        "scanner_coupled": False,
        "shadow_coupled": False,
        "trade_recommendation": False,
    }
