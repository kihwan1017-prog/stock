"""Admin UPBIT News/Notice Collector + Symbol Mapping API (N2/N3)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.news.collector_constants import (
    SOURCE_CODE_CRYPTO_NEWS,
    SOURCE_CODE_UPBIT_NOTICE,
)
from stock_platform.news.collector_scheduler import (
    upbit_news_notice_collector_scheduler,
)
from stock_platform.news.crypto_news_collector import resolve_crypto_news_provider
from stock_platform.news.repository import NewsRepository
from stock_platform.news.symbol_mapper import (
    NewsSymbolMapper,
    mapping_status_snapshot,
)


router = APIRouter(
    prefix="/api/v1/admin/upbit/news-collector",
    tags=["Admin Upbit News Collector"],
    dependencies=[Depends(require_admin)],
)


class CollectorRunRequest(BaseModel):
    include_notice: bool = True
    include_crypto: bool = True


class SymbolMappingRunRequest(BaseModel):
    include_notice: bool = True
    include_crypto: bool = True
    limit: int | None = None


@router.get("/status")
def collector_status(session: Session = Depends(get_db_session)) -> dict:
    status = upbit_news_notice_collector_scheduler.status()
    status["crypto_provider"] = resolve_crypto_news_provider().__dict__
    status["symbol_mapping"] = mapping_status_snapshot(session)
    return status


@router.get("/recent")
def list_recent_notices(
    limit: int = Query(default=20, ge=1, le=100),
    source: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict:
    codes = [SOURCE_CODE_UPBIT_NOTICE, SOURCE_CODE_CRYPTO_NEWS]
    if source:
        codes = [source.strip().upper()]
    pairs = NewsRepository(session).list_mappings_with_articles(
        source_codes=codes,
        limit=limit,
    )
    items = []
    for row, links in pairs:
        raw = row.raw_data if isinstance(row.raw_data, dict) else {}
        sm = raw.get("symbol_mapping") if isinstance(raw, dict) else {}
        mapped_symbols = []
        for link in links:
            mapped_symbols.append(
                {
                    "symbol": link.symbol,
                    "match_type": link.match_type,
                    "mapping_confidence": float(link.relevance_score),
                    "market_code": link.market_code,
                }
            )
        # evidence 보강 (raw_data)
        evidence_by_symbol = {}
        if isinstance(sm, dict):
            for ev in sm.get("mappings") or []:
                if isinstance(ev, dict) and ev.get("symbol"):
                    evidence_by_symbol[str(ev["symbol"]).upper()] = ev
        for item in mapped_symbols:
            ev = evidence_by_symbol.get(str(item["symbol"]).upper())
            if ev:
                item["matched_alias"] = ev.get("matched_alias")
                item["matched_field"] = ev.get("matched_field")
                item["resolver_version"] = ev.get("resolver_version")
                item["quality_status"] = ev.get("quality_status")
                item["quality_reason"] = ev.get("quality_reason")
                item["review_required"] = ev.get("review_required")
                item["review_reason"] = ev.get("review_reason")
                item["quality_policy_version"] = ev.get(
                    "quality_policy_version"
                )

        items.append(
            {
                "article_id": row.article_id,
                "source": row.source_code,
                "source_type": raw.get("source_type"),
                "external_id": raw.get("external_id"),
                "title": row.title,
                "url": row.original_link,
                "canonical_url": raw.get("canonical_url") or row.original_link,
                "published_at": (
                    row.published_at.isoformat() if row.published_at else None
                ),
                "collected_at": (
                    row.created_at.isoformat() if row.created_at else None
                ),
                "category": raw.get("category"),
                "language": raw.get("language"),
                "status": raw.get("status"),
                "mapping_status": (
                    sm.get("status") if isinstance(sm, dict) else None
                ),
                "mapped_symbols": mapped_symbols,
                # AI/sentiment/score 미노출
            }
        )
    return {
        "items": items,
        "count": len(items),
        "symbol_mapping": True,
        "ai_analysis": False,
    }


@router.post("/run")
async def run_collector_once(body: CollectorRunRequest | None = None) -> dict:
    """수동 1회 READ collection — AI/Scanner/Shadow/주문 없음."""

    req = body or CollectorRunRequest()
    result = await upbit_news_notice_collector_scheduler.run_once_now(
        include_notice=bool(req.include_notice),
        include_crypto=bool(req.include_crypto),
    )
    return {
        "status": upbit_news_notice_collector_scheduler.status(),
        "result": result,
    }


@router.get("/symbol-mapping/status")
def symbol_mapping_status(
    session: Session = Depends(get_db_session),
) -> dict:
    return mapping_status_snapshot(session)


@router.post("/symbol-mapping/run")
def run_symbol_mapping(
    body: SymbolMappingRunRequest | None = None,
    session: Session = Depends(get_db_session),
) -> dict:
    """News Article → Symbol Mapping only. Scanner/AI/Shadow/Trading 금지."""

    req = body or SymbolMappingRunRequest()
    codes: list[str] = []
    if req.include_notice:
        codes.append(SOURCE_CODE_UPBIT_NOTICE)
    if req.include_crypto:
        codes.append(SOURCE_CODE_CRYPTO_NEWS)
    if not codes:
        return {"error": "NO_SOURCE_SELECTED", "result": None}

    mapper = NewsSymbolMapper(session)
    stats = mapper.run_backfill(source_codes=codes, limit=req.limit)
    return {
        "result": asdict(stats),
        "status": mapping_status_snapshot(session),
        "ai_calls": 0,
        "scanner_mutated": False,
        "shadow_mutated": False,
        "orders_created": 0,
    }
