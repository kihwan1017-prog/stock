"""Admin UPBIT News/Notice Collector API — COLLECT only (N2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
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


router = APIRouter(
    prefix="/api/v1/admin/upbit/news-collector",
    tags=["Admin Upbit News Collector"],
    dependencies=[Depends(require_admin)],
)


class CollectorRunRequest(BaseModel):
    include_notice: bool = True
    include_crypto: bool = True


@router.get("/status")
def collector_status() -> dict:
    status = upbit_news_notice_collector_scheduler.status()
    status["crypto_provider"] = resolve_crypto_news_provider().__dict__
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
    rows = NewsRepository(session).list_by_source_codes(
        source_codes=codes,
        limit=limit,
    )
    items = []
    for row in rows:
        raw = row.raw_data if isinstance(row.raw_data, dict) else {}
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
                # N2 금지 필드 미노출: symbol/sentiment/AI/score
            }
        )
    return {
        "items": items,
        "count": len(items),
        "symbol_mapping": False,
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
