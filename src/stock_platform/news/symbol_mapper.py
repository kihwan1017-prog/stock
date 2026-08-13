"""STEP N3 — News/Notice → Symbol Mapping 저장 (AI/Scanner 무관)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.news.collector_constants import (
    PLACEHOLDER_SYMBOL_CRYPTO,
    PLACEHOLDER_SYMBOL_NOTICE,
    SOURCE_CODE_CRYPTO_NEWS,
    SOURCE_CODE_UPBIT_NOTICE,
)
from stock_platform.news.models import NewsArticle
from stock_platform.news.repository import NewsRepository
from stock_platform.news.symbol_mapping_constants import (
    MARKET_CODE_UPBIT,
    MATCH_BODY_ONLY_ALIAS,
    MATCH_ENGLISH_NAME,
    MATCH_EXACT_BASE_SYMBOL,
    MATCH_EXACT_MARKET_SYMBOL,
    MATCH_KOREAN_NAME,
    RESOLVER_VERSION,
    STATUS_AMBIGUOUS,
    STATUS_MAPPED,
    STATUS_PARTIAL,
    STATUS_UNMAPPED,
)
from stock_platform.news.symbol_mapping_quality import (
    apply_quality_to_evidence,
    build_general_word_collision_set,
    classify_mapping_quality,
)
from stock_platform.news.symbol_mapping_quality_constants import (
    QUALITY_AMBIGUOUS,
    QUALITY_POLICY_VERSION,
    QUALITY_REJECTED,
    QUALITY_REVIEW_REQUIRED,
    QUALITY_TRUSTED,
    N4_CONSUMABLE_QUALITY,
)
from stock_platform.news.symbol_resolver import (
    AliasEntry,
    InstrumentAlias,
    SymbolMatch,
    resolve_symbols,
)
from stock_platform.news.symbol_universe import load_alias_index


_RESOLVER_MATCH_TYPES = frozenset(
    {
        MATCH_EXACT_MARKET_SYMBOL,
        MATCH_EXACT_BASE_SYMBOL,
        MATCH_KOREAN_NAME,
        MATCH_ENGLISH_NAME,
        MATCH_BODY_ONLY_ALIAS,
    }
)


_PLACEHOLDERS = frozenset(
    {
        PLACEHOLDER_SYMBOL_NOTICE.upper(),
        PLACEHOLDER_SYMBOL_CRYPTO.upper(),
        "_NOTICE_",
        "_CRYPTO_",
    }
)


@dataclass
class MappingRunStats:
    articles_scanned: int = 0
    mapped_articles: int = 0
    unmapped_articles: int = 0
    ambiguous_articles: int = 0
    partial_articles: int = 0
    mapping_count: int = 0
    symbols_count: int = 0
    duplicates_skipped: int = 0
    updated_count: int = 0
    errors: int = 0
    universe_count: int = 0
    alias_count: int = 0
    resolver_version: str = RESOLVER_VERSION
    quality_policy_version: str = QUALITY_POLICY_VERSION
    quality_trusted: int = 0
    quality_review_required: int = 0
    quality_ambiguous: int = 0
    quality_rejected: int = 0
    body_only_total: int = 0
    body_only_trusted: int = 0
    body_only_review: int = 0
    body_only_rejected: int = 0
    body_only_ambiguous: int = 0
    by_source: dict[str, dict[str, int]] = field(default_factory=dict)
    by_match_type: dict[str, int] = field(default_factory=dict)
    by_confidence_bucket: dict[str, int] = field(default_factory=dict)
    by_quality_status: dict[str, int] = field(default_factory=dict)
    top_symbols: list[dict[str, Any]] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)
    false_positive_review: list[dict[str, Any]] = field(default_factory=list)
    n4_consumable_contract: str = "quality_status==TRUSTED"


class NewsSymbolMapper:
    """Article → symbol links only. Scanner/Shadow/AI import 금지."""

    def __init__(
        self,
        session: Session,
        *,
        repository: NewsRepository | None = None,
        aliases: list[AliasEntry] | None = None,
        instruments: list[InstrumentAlias] | None = None,
        universe_count: int | None = None,
    ) -> None:
        self._session = session
        self._repository = repository or NewsRepository(session)
        if aliases is None:
            loaded_instruments, aliases = load_alias_index(
                session, active_only=True
            )
            self._instruments = loaded_instruments
            self._aliases = aliases
            self._universe_count = len(loaded_instruments)
        else:
            self._aliases = aliases
            self._instruments = list(instruments or [])
            self._universe_count = int(
                universe_count or len(self._instruments)
            )
        self._collision_aliases = build_general_word_collision_set(
            self._instruments
        )

    def map_article(
        self,
        article: NewsArticle,
        *,
        reconcile: bool = True,
    ) -> dict[str, Any]:
        title = article.title or ""
        body = self._extract_body(article)
        result = resolve_symbols(
            title=title,
            body=body,
            aliases=self._aliases,
        )

        # placeholder 는 mapping 결과로 절대 저장하지 않음
        safe_mappings = [
            m
            for m in result.mappings
            if m.symbol.upper() not in _PLACEHOLDERS
            and not m.symbol.upper().startswith("_")
            and m.symbol.upper().startswith("KRW-")
        ]

        inserted = 0
        updated = 0
        skipped = 0
        evidence_rows: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat()
        keep_symbols = {m.symbol.upper() for m in safe_mappings}

        for match in safe_mappings:
            evidence = {
                "symbol": match.symbol,
                "matched_alias": match.matched_alias,
                "match_type": match.match_type,
                "matched_field": match.matched_field,
                "mapping_confidence": match.mapping_confidence,
                "resolver_version": RESOLVER_VERSION,
                "created_at": now,
            }
            decision = classify_mapping_quality(
                match=match,
                title=title,
                body=body,
                source_code=str(article.source_code or ""),
                collision_aliases=self._collision_aliases,
                article_ambiguous=bool(result.ambiguous),
            )
            evidence = apply_quality_to_evidence(evidence, decision)
            evidence_rows.append(evidence)
            action = self._repository.upsert_symbol_mapping_link(
                article_id=int(article.article_id),
                market_code=MARKET_CODE_UPBIT,
                symbol=match.symbol,
                match_type=match.match_type,
                relevance_score=Decimal(str(match.mapping_confidence)),
            )
            if action == "inserted":
                inserted += 1
            elif action == "updated":
                updated += 1
            else:
                skipped += 1

        reconciled = 0
        if reconcile:
            reconciled = self._repository.reconcile_resolver_links(
                article_id=int(article.article_id),
                keep_symbols=keep_symbols,
                resolver_match_types=set(_RESOLVER_MATCH_TYPES),
            )

        status = result.status
        if safe_mappings and result.ambiguous:
            status = STATUS_PARTIAL
        elif safe_mappings:
            status = STATUS_MAPPED
        elif result.ambiguous:
            status = STATUS_AMBIGUOUS
        else:
            status = STATUS_UNMAPPED

        quality_counts = {
            QUALITY_TRUSTED: 0,
            QUALITY_REVIEW_REQUIRED: 0,
            QUALITY_AMBIGUOUS: 0,
            QUALITY_REJECTED: 0,
        }
        for ev in evidence_rows:
            qs = str(ev.get("quality_status") or "")
            if qs in quality_counts:
                quality_counts[qs] += 1

        raw = dict(article.raw_data) if isinstance(article.raw_data, dict) else {}
        # 이전 evidence history 보존
        prev_sm = raw.get("symbol_mapping") if isinstance(raw.get("symbol_mapping"), dict) else {}
        history = []
        if isinstance(prev_sm, dict) and prev_sm.get("mappings"):
            history = list(prev_sm.get("quality_history") or [])
            history.append(
                {
                    "mapped_at": prev_sm.get("mapped_at"),
                    "quality_policy_version": prev_sm.get(
                        "quality_policy_version"
                    ),
                    "mapping_count": len(prev_sm.get("mappings") or []),
                }
            )
            history = history[-5:]

        raw["symbol_mapping"] = {
            "status": status,
            "resolver_version": RESOLVER_VERSION,
            "quality_policy_version": QUALITY_POLICY_VERSION,
            "mapped_at": now,
            "mappings": evidence_rows,
            "ambiguous": result.ambiguous,
            "quality_counts": quality_counts,
            "n4_consumable_symbols": [
                ev["symbol"]
                for ev in evidence_rows
                if ev.get("quality_status") in N4_CONSUMABLE_QUALITY
            ],
            "inserted": inserted,
            "updated": updated,
            "duplicates_skipped": skipped,
            "reconciled_removed": reconciled,
            "quality_history": history,
        }
        article.raw_data = raw
        self._session.flush()

        return {
            "article_id": int(article.article_id),
            "source": article.source_code,
            "title": article.title,
            "status": status,
            "mappings": evidence_rows,
            "ambiguous": result.ambiguous,
            "inserted": inserted,
            "updated": updated,
            "duplicates_skipped": skipped,
            "reconciled_removed": reconciled,
            "quality_counts": quality_counts,
        }

    def run_backfill(
        self,
        *,
        source_codes: list[str] | None = None,
        limit: int | None = None,
        article_ids: list[int] | None = None,
    ) -> MappingRunStats:
        codes = source_codes or [
            SOURCE_CODE_UPBIT_NOTICE,
            SOURCE_CODE_CRYPTO_NEWS,
        ]
        stats = MappingRunStats(
            universe_count=self._universe_count,
            alias_count=len(self._aliases),
        )
        symbol_freq: dict[str, int] = {}

        if article_ids:
            articles = self._repository.get_articles_by_ids(article_ids)
        else:
            articles = self._repository.list_by_source_codes(
                source_codes=codes,
                limit=limit or 10_000,
            )

        for article in articles:
            stats.articles_scanned += 1
            source = str(article.source_code or "").upper()
            src_bucket = stats.by_source.setdefault(
                source,
                {
                    "scanned": 0,
                    "mapped": 0,
                    "unmapped": 0,
                    "ambiguous": 0,
                    "partial": 0,
                    "mapping_count": 0,
                },
            )
            src_bucket["scanned"] += 1
            try:
                out = self.map_article(article)
            except Exception as exc:  # noqa: BLE001 — isolation
                stats.errors += 1
                logger.warning(
                    "news_symbol_mapping_failed",
                    article_id=getattr(article, "article_id", None),
                    error=str(exc)[:200],
                )
                continue

            status = out["status"]
            if status == STATUS_MAPPED:
                stats.mapped_articles += 1
                src_bucket["mapped"] += 1
            elif status == STATUS_PARTIAL:
                stats.partial_articles += 1
                stats.mapped_articles += 1
                src_bucket["partial"] += 1
                src_bucket["mapped"] += 1
            elif status == STATUS_AMBIGUOUS:
                stats.ambiguous_articles += 1
                src_bucket["ambiguous"] += 1
            else:
                stats.unmapped_articles += 1
                src_bucket["unmapped"] += 1

            mappings = out.get("mappings") or []
            stats.mapping_count += len(mappings)
            src_bucket["mapping_count"] += len(mappings)
            stats.duplicates_skipped += int(out.get("duplicates_skipped") or 0)
            stats.updated_count += int(out.get("updated") or 0)

            for m in mappings:
                sym = str(m.get("symbol") or "")
                symbol_freq[sym] = symbol_freq.get(sym, 0) + 1
                mt = str(m.get("match_type") or "")
                stats.by_match_type[mt] = stats.by_match_type.get(mt, 0) + 1
                conf = float(m.get("mapping_confidence") or 0)
                bucket = _confidence_bucket(conf)
                stats.by_confidence_bucket[bucket] = (
                    stats.by_confidence_bucket.get(bucket, 0) + 1
                )
                qs = str(m.get("quality_status") or "")
                stats.by_quality_status[qs] = (
                    stats.by_quality_status.get(qs, 0) + 1
                )
                if qs == QUALITY_TRUSTED:
                    stats.quality_trusted += 1
                elif qs == QUALITY_REVIEW_REQUIRED:
                    stats.quality_review_required += 1
                elif qs == QUALITY_AMBIGUOUS:
                    stats.quality_ambiguous += 1
                elif qs == QUALITY_REJECTED:
                    stats.quality_rejected += 1

                if mt == MATCH_BODY_ONLY_ALIAS or str(
                    m.get("matched_field")
                ).upper() == "BODY":
                    stats.body_only_total += 1
                    if qs == QUALITY_TRUSTED:
                        stats.body_only_trusted += 1
                    elif qs == QUALITY_REVIEW_REQUIRED:
                        stats.body_only_review += 1
                    elif qs == QUALITY_REJECTED:
                        stats.body_only_rejected += 1
                    elif qs == QUALITY_AMBIGUOUS:
                        stats.body_only_ambiguous += 1

            if len(stats.samples) < 10 and mappings:
                stats.samples.append(
                    {
                        "article_id": out["article_id"],
                        "source": out["source"],
                        "title": out["title"],
                        "status": status,
                        "symbols": [m["symbol"] for m in mappings],
                        "mappings": mappings,
                    }
                )

            # FP 검토: REJECTED/REVIEW + collision / 관심 심볼
            risk_syms = {
                "KRW-AUCTION",
                "KRW-GAS",
                "KRW-ONE",
                "KRW-ME",
                "KRW-ID",
            }
            for m in mappings:
                qs = str(m.get("quality_status") or "")
                sym = str(m.get("symbol") or "").upper()
                if (
                    sym in risk_syms
                    or qs in {QUALITY_REJECTED, QUALITY_REVIEW_REQUIRED}
                    or m.get("general_word_collision")
                ):
                    if len(stats.false_positive_review) < 20:
                        body = self._extract_body(article)
                        alias = str(m.get("matched_alias") or "")
                        excerpt = _context_excerpt(
                            f"{article.title or ''}\n{body}", alias
                        )
                        stats.false_positive_review.append(
                            {
                                "article_id": out["article_id"],
                                "title": out["title"],
                                "symbol": sym,
                                "matched_alias": alias,
                                "context_excerpt": excerpt,
                                "match_type": m.get("match_type"),
                                "matched_field": m.get("matched_field"),
                                "old_confidence": m.get("mapping_confidence"),
                                "new_quality_status": qs,
                                "reason": m.get("quality_reason"),
                            }
                        )

        stats.symbols_count = len(symbol_freq)
        stats.top_symbols = [
            {"symbol": s, "count": c}
            for s, c in sorted(
                symbol_freq.items(), key=lambda x: (-x[1], x[0])
            )[:20]
        ]

        self._session.commit()
        return stats

    @staticmethod
    def _extract_body(article: NewsArticle) -> str:
        parts: list[str] = []
        if article.description:
            parts.append(str(article.description))
        raw = article.raw_data if isinstance(article.raw_data, dict) else {}
        for key in ("normalized_text", "body", "content"):
            val = raw.get(key)
            if val:
                parts.append(str(val))
        return "\n".join(parts)


def _confidence_bucket(conf: float) -> str:
    if conf >= 0.95:
        return "0.95-1.00"
    if conf >= 0.90:
        return "0.90-0.94"
    if conf >= 0.80:
        return "0.80-0.89"
    return "below-0.80"


def _context_excerpt(text: str, alias: str, *, radius: int = 60) -> str:
    if not text:
        return ""
    if not alias:
        return text[:120]
    lower = text.lower()
    idx = lower.find(alias.lower())
    if idx < 0:
        return text[:120]
    start = max(0, idx - radius)
    end = min(len(text), idx + len(alias) + radius)
    return text[start:end].replace("\n", " ").strip()


def mapping_status_snapshot(session: Session) -> dict[str, Any]:
    """Admin status — Scanner/Shadow 읽지 않음."""

    instruments, aliases = load_alias_index(session, active_only=True)
    collisions = build_general_word_collision_set(instruments)
    repo = NewsRepository(session)
    articles = repo.list_by_source_codes(
        source_codes=[SOURCE_CODE_UPBIT_NOTICE, SOURCE_CODE_CRYPTO_NEWS],
        limit=5000,
    )
    mapped = unmapped = ambiguous = partial = 0
    link_count = 0
    q_trusted = q_review = q_amb = q_rej = 0
    for article in articles:
        raw = article.raw_data if isinstance(article.raw_data, dict) else {}
        sm = raw.get("symbol_mapping") if isinstance(raw, dict) else None
        status = None
        if isinstance(sm, dict):
            status = sm.get("status")
            for ev in sm.get("mappings") or []:
                if not isinstance(ev, dict):
                    continue
                qs = str(ev.get("quality_status") or "")
                if qs == QUALITY_TRUSTED:
                    q_trusted += 1
                elif qs == QUALITY_REVIEW_REQUIRED:
                    q_review += 1
                elif qs == QUALITY_AMBIGUOUS:
                    q_amb += 1
                elif qs == QUALITY_REJECTED:
                    q_rej += 1
        if status == STATUS_MAPPED:
            mapped += 1
        elif status == STATUS_PARTIAL:
            partial += 1
            mapped += 1
        elif status == STATUS_AMBIGUOUS:
            ambiguous += 1
        elif status == STATUS_UNMAPPED:
            unmapped += 1
        links = repo.list_symbol_links([int(article.article_id)])
        link_count += sum(
            1
            for ln in links
            if str(ln.symbol).upper() not in _PLACEHOLDERS
            and str(ln.symbol).upper().startswith("KRW-")
        )

    return {
        "resolver_version": RESOLVER_VERSION,
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "universe_count": len(instruments),
        "alias_count": len(aliases),
        "general_word_collision_count": len(collisions),
        "articles_total": len(articles),
        "mapped_articles": mapped,
        "unmapped_articles": unmapped,
        "ambiguous_articles": ambiguous,
        "partial_articles": partial,
        "mapping_link_count": link_count,
        "quality_trusted": q_trusted,
        "quality_review_required": q_review,
        "quality_ambiguous": q_amb,
        "quality_rejected": q_rej,
        "n4_consumable_contract": "quality_status==TRUSTED",
        "ai_analysis": False,
        "scanner_coupled": False,
        "shadow_coupled": False,
    }
