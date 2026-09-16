"""Admin UPBIT News Signal API — INFORMATIONAL ONLY (N5)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.news.news_signal_scheduler import (
    upbit_news_signal_scheduler,
)
from stock_platform.news.news_signal_service import (
    NewsSignalService,
    list_recent_signals,
    signal_stats_snapshot,
    signal_status_snapshot,
)


router = APIRouter(
    prefix="/api/v1/admin/upbit/news-signals",
    tags=["Admin Upbit News Signals"],
    dependencies=[Depends(require_admin)],
)


class NewsSignalRunRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    analysis_ids: list[int] | None = None
    force: bool = False


@router.get("/status")
def news_signals_status(session: Session = Depends(get_db_session)) -> dict:
    snap = signal_status_snapshot(session)
    snap["scheduler"] = upbit_news_signal_scheduler.status()
    return snap


@router.get("/recent")
def news_signals_recent(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> dict:
    items = list_recent_signals(session, limit=limit)
    return {
        "items": items,
        "count": len(items),
        "informational_only": True,
        "trade_recommendation": False,
        "scanner_apply": False,
        "combined_score": False,
        "ai_gate": False,
        "llm_calls": 0,
    }


@router.get("/stats")
def news_signals_stats(session: Session = Depends(get_db_session)) -> dict:
    return signal_stats_snapshot(session)


@router.post("/run")
def news_signals_run(
    body: NewsSignalRunRequest | None = None,
    session: Session = Depends(get_db_session),
) -> dict:
    """COMPLETED N4 → News Signal only. Scanner/Shadow/Trading mutation 없음."""

    req = body or NewsSignalRunRequest()
    service = NewsSignalService(session)
    stats = service.run_batch(
        limit=req.limit,
        analysis_ids=req.analysis_ids,
        force=bool(req.force),
    )
    return {
        "result": asdict(stats),
        "status": signal_status_snapshot(session),
        "scheduler": upbit_news_signal_scheduler.status(),
        "llm_calls": 0,
        "scanner_mutated": False,
        "shadow_mutated": False,
        "combined_score": False,
        "orders_created": 0,
        "informational_only": True,
    }
