"""Admin UPBIT AI News Analysis API — INFORMATIONAL ONLY (N4)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.news.news_ai_analysis_scheduler import (
    upbit_news_ai_analysis_scheduler,
)
from stock_platform.news.news_ai_analysis_service import (
    NewsAIAnalysisService,
    analysis_status_snapshot,
    list_recent_analyses,
)


router = APIRouter(
    prefix="/api/v1/admin/upbit/news-analysis",
    tags=["Admin Upbit News AI Analysis"],
    dependencies=[Depends(require_admin)],
)


class NewsAnalysisRunRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=5)
    article_ids: list[int] | None = None
    force: bool = False


@router.get("/status")
def news_analysis_status(session: Session = Depends(get_db_session)) -> dict:
    snap = analysis_status_snapshot(session)
    snap["scheduler"] = upbit_news_ai_analysis_scheduler.status()
    return snap


@router.get("/recent")
def news_analysis_recent(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> dict:
    items = list_recent_analyses(session, limit=limit)
    return {
        "items": items,
        "count": len(items),
        "informational_only": True,
        "trade_recommendation": False,
        "ai_analysis": True,
        "scanner_apply": False,
    }


@router.post("/run")
async def news_analysis_run(
    body: NewsAnalysisRunRequest | None = None,
    session: Session = Depends(get_db_session),
) -> dict:
    """수동 AI News Analysis — Scanner/Shadow/Trading mutation 없음."""

    req = body or NewsAnalysisRunRequest()
    service = NewsAIAnalysisService(session)
    try:
        stats = await service.run_batch(
            limit=req.limit,
            article_ids=req.article_ids,
            force=bool(req.force),
        )
    finally:
        await service.aclose()
    return {
        "result": asdict(stats),
        "status": analysis_status_snapshot(session),
        "scheduler": upbit_news_ai_analysis_scheduler.status(),
        "ai_calls": stats.ai_calls,
        "scanner_mutated": False,
        "shadow_mutated": False,
        "orders_created": 0,
        "informational_only": True,
    }
